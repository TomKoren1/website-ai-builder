import hashlib
import json
import logging
import secrets
import time
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
from app.metrics import (
    chat_requests_in_progress,
    deployment_callbacks_total,
    llm_request_duration_seconds,
    llm_requests_total,
)
from app.models import ApiKey, Conversation, Deployment, Domain, Message, Project, User
from app.schemas import (
    ChatRequest,
    ChatResponse,
    DeploymentCallback,
    DeploymentOut,
    FileChange,
    MessageOut,
    PushRequest,
)
from app.security.csrf import verify_csrf
from app.security.deps import get_current_user
from app.utils.paths import is_safe_project_path

_CI_WORKFLOW_FILE = "deploy.yml"

logger = logging.getLogger(__name__)

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
    chat_requests_in_progress.inc()
    try:
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
        start = time.perf_counter()
        try:
            raw_reply = await provider.generate(plaintext_key, _SYSTEM_PROMPT, history)
        except Exception:
            llm_requests_total.labels(provider=body.provider, outcome="error").inc()
            raise
        finally:
            llm_request_duration_seconds.labels(provider=body.provider).observe(time.perf_counter() - start)

        try:
            # Models routinely ignore "respond with JSON and nothing else" and wrap the
            # object in a ```json ... ``` fence anyway — strip that before parsing rather
            # than treating every fenced reply as malformed.
            candidate = raw_reply.strip()
            if candidate.startswith("```"):
                candidate = candidate.split("\n", 1)[1] if "\n" in candidate else ""
                candidate = candidate.rsplit("```", 1)[0].strip()

            parsed = json.loads(candidate)
            files = [FileChange(**f) for f in parsed["files"]]
            reply_text = parsed["reply"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            llm_requests_total.labels(provider=body.provider, outcome="error").inc()
            logger.warning("Model returned unparsable reply for provider=%s: %r", body.provider, raw_reply[:500])
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="Model returned a malformed response"
            ) from exc

        unsafe = [f.path for f in files if not is_safe_project_path(f.path)]
        if unsafe:
            llm_requests_total.labels(provider=body.provider, outcome="error").inc()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Model returned unsafe file path(s): {unsafe}",
            )

        llm_requests_total.labels(provider=body.provider, outcome="success").inc()

        db.add(Message(conversation_id=conversation.id, role="user", content=body.message))
        db.add(Message(conversation_id=conversation.id, role="assistant", content=raw_reply))
        api_key_row.last_used_at = datetime.now(timezone.utc)
        await db.commit()

        return ChatResponse(reply=reply_text, proposed_files=files)
    finally:
        chat_requests_in_progress.dec()


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

    # A project's bucket doesn't exist until its first domain is registered
    # (POST /domains — see that router for why bucket creation happens
    # there, not here). Nothing to sync to yet just means the commit lands
    # in Git but nothing deploys — not an error, just an incomplete setup.
    domain = await db.scalar(select(Domain).where(Domain.project_id == project_id))

    deployment = Deployment(
        project_id=project_id,
        git_commit_sha=commit_sha,
        status="pending" if domain else "success",
        deployed_at=None if domain else datetime.now(timezone.utc),
    )

    if domain:
        # One-time token: hashed at rest (same pattern as refresh tokens —
        # see security/jwt.py), handed to the CI job via workflow_dispatch
        # inputs rather than ever being committed to the repo. See
        # DeploymentCallback / the callback endpoint below for the other
        # half — it's nulled out there so it can't be replayed.
        raw_token = secrets.token_urlsafe(32)
        deployment.callback_token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    db.add(deployment)
    await db.commit()
    await db.refresh(deployment)

    if domain:
        await gitea_client.dispatch_workflow(
            project.git_repo_path,
            _CI_WORKFLOW_FILE,
            {
                "bucket_name": domain.s3_bucket_name,
                "project_id": str(project_id),
                "deployment_id": str(deployment.id),
                "callback_token": raw_token,
            },
        )

    return deployment


@router.post("/deployments/{deployment_id}/callback", include_in_schema=False)
async def deployment_callback(
    project_id: uuid.UUID,
    deployment_id: uuid.UUID,
    body: DeploymentCallback,
    db: AsyncSession = Depends(get_db),
):
    # No get_current_user/CSRF here on purpose — the CI job calling this
    # isn't a logged-in browser session, it authenticates purely via the
    # token. See DeploymentCallback's docstring.
    deployment = await db.get(Deployment, deployment_id)
    if (
        deployment is None
        or deployment.project_id != project_id
        or deployment.callback_token_hash is None
        or not secrets.compare_digest(
            deployment.callback_token_hash, hashlib.sha256(body.token.encode()).hexdigest()
        )
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")

    if body.status not in ("success", "failed"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")

    deployment.status = body.status
    deployment.deployed_at = datetime.now(timezone.utc)
    deployment.callback_token_hash = None  # single-use — a replay of this same callback now 404s
    await db.commit()

    deployment_callbacks_total.labels(status=body.status).inc()

    return {"ok": True}
