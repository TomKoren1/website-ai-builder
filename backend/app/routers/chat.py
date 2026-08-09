import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import gitea_client
from app.crypto import decrypt_api_key
from app.db import get_db
from app.llm.base import ChatMessage
from app.llm.registry import get_provider
from app.models import ApiKey, Conversation, Deployment, Message, Project, User
from app.schemas import ChatRequest, ChatResponse, DeploymentOut, FileChange, MessageOut, PushRequest
from app.security.csrf import verify_csrf
from app.security.deps import get_current_user
from app.utils.paths import is_safe_project_path

router = APIRouter(prefix="/projects/{project_id}", tags=["chat"])

# The model has no other channel for returning file changes, so the output
# contract is enforced entirely through this prompt plus the JSON parse +
# path-safety check below. There's no schema enforcement at the API level
# (that would mean provider-specific structured-output code per adapter) —
# a malformed response surfaces as a 502 rather than corrupting a project.
_SYSTEM_PROMPT = """You are an AI website builder assistant. The user describes changes they \
want to their static website (plain HTML/CSS/JS only — no build step, no frameworks requiring \
compilation). Respond with a single JSON object and nothing else, matching exactly this shape:
{"reply": "<short human-readable summary of what changed>", "files": [{"path": "<relative file path>", "content": "<full file content>"}]}
Only include files you are creating or changing. Paths must be relative (e.g. "index.html", \
"css/style.css") and must never contain ".." or start with "/"."""


async def _get_owned_project(project_id: uuid.UUID, user: User, db: AsyncSession) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


async def _get_or_create_conversation(project_id: uuid.UUID, db: AsyncSession) -> Conversation:
    conversation = await db.scalar(select(Conversation).where(Conversation.project_id == project_id))
    if conversation is None:
        conversation = Conversation(project_id=project_id)
        db.add(conversation)
        await db.flush()
    return conversation


@router.get("/messages", response_model=list[MessageOut])
async def get_messages(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # How the frontend reconstructs chat history + accumulated files on
    # page load — without this, every reload starts from empty React
    # state even though the backend has the full conversation all along.
    await _get_owned_project(project_id, user, db)
    conversation = await db.scalar(select(Conversation).where(Conversation.project_id == project_id))
    if conversation is None:
        return []
    rows = await db.scalars(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
    )
    return rows.all()


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_csrf)])
async def chat(
    project_id: uuid.UUID,
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_project(project_id, user, db)

    api_key_row = await db.scalar(
        select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.provider == body.provider)
    )
    if api_key_row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No API key stored for provider {body.provider!r} — add one first",
        )

    # Decrypted only for the duration of this one call; never cached, logged, or returned.
    plaintext_key = decrypt_api_key(api_key_row.ciphertext, api_key_row.encrypted_dek, api_key_row.nonce)

    conversation = await _get_or_create_conversation(project_id, db)
    history_rows = await db.scalars(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
    )
    history = [ChatMessage(role=m.role, content=m.content) for m in history_rows]
    history.append(ChatMessage(role="user", content=body.message))

    provider = get_provider(body.provider)
    raw_reply = await provider.generate(plaintext_key, _SYSTEM_PROMPT, history)

    try:
        parsed = json.loads(raw_reply)
        files = [FileChange(**f) for f in parsed["files"]]
        reply_text = parsed["reply"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Model returned a malformed response"
        ) from exc

    unsafe = [f.path for f in files if not is_safe_project_path(f.path)]
    if unsafe:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Model returned unsafe file path(s): {unsafe}",
        )

    db.add(Message(conversation_id=conversation.id, role="user", content=body.message))
    db.add(Message(conversation_id=conversation.id, role="assistant", content=raw_reply))
    api_key_row.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    return ChatResponse(reply=reply_text, proposed_files=files)


@router.post("/push", response_model=DeploymentOut, dependencies=[Depends(verify_csrf)])
async def push(
    project_id: uuid.UUID,
    body: PushRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(project_id, user, db)

    unsafe = [f.path for f in body.files if not is_safe_project_path(f.path)]
    if unsafe:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsafe file path(s): {unsafe}")

    commit_sha = await gitea_client.commit_files(
        project.git_repo_path,
        {f.path: f.content for f in body.files},
        body.commit_message,
    )

    # Phase 4 wires this up to real CI/CD status callbacks; for now the
    # commit succeeding synchronously is the only signal we have.
    deployment = Deployment(
        project_id=project_id,
        git_commit_sha=commit_sha,
        status="success",
        deployed_at=datetime.now(timezone.utc),
    )
    db.add(deployment)
    await db.commit()
    await db.refresh(deployment)
    return deployment
