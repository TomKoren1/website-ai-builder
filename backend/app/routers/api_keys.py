import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import encrypt_api_key
from app.db import get_db
from app.models import ApiKey, User
from app.schemas import ApiKeyCreate, ApiKeyOut
from app.security.csrf import verify_csrf
from app.security.deps import get_current_user

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


def _display_hint(raw: str) -> str:
    if len(raw) <= 8:
        return "*" * len(raw)
    return f"{raw[:4]}...{raw[-4:]}"


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(ApiKey).where(ApiKey.user_id == user.id))
    return result.all()


@router.post(
    "", response_model=ApiKeyOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_csrf)]
)
async def create_api_key(
    body: ApiKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.scalar(
        select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.provider == body.provider)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"A key for {body.provider} already exists"
        )

    ciphertext, encrypted_dek, nonce = encrypt_api_key(body.api_key)
    key = ApiKey(
        user_id=user.id,
        provider=body.provider,
        display_hint=_display_hint(body.api_key),
        ciphertext=ciphertext,
        encrypted_dek=encrypted_dek,
        nonce=nonce,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_csrf)])
async def delete_api_key(
    key_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    key = await db.get(ApiKey, key_id)
    if key is None or key.user_id != user.id:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.delete(key)
    await db.commit()
