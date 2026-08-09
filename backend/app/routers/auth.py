from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Session as SessionModel
from app.models import User
from app.schemas import LoginRequest, RegisterRequest, TokenResponse
from app.security.jwt import create_access_token, generate_refresh_token, hash_refresh_token
from app.security.passwords import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

_ACCESS_COOKIE = "access_token"
_REFRESH_COOKIE = "refresh_token"


def _set_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        _ACCESS_COOKIE,
        access_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.jwt_access_token_ttl_minutes * 60,
    )
    # Scoped to /auth/refresh only — the browser never needs to send the
    # refresh token to any other endpoint, so it isn't attached to every
    # request the way the access token cookie is.
    response.set_cookie(
        _REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.jwt_refresh_token_ttl_days * 24 * 60 * 60,
        path="/auth/refresh",
    )


async def _issue_session(db: AsyncSession, user_id: UUID) -> tuple[str, str]:
    access_token = create_access_token(user_id)
    raw_refresh, hashed_refresh = generate_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_ttl_days)
    db.add(SessionModel(user_id=user_id, refresh_token_hash=hashed_refresh, expires_at=expires_at))
    await db.commit()
    return access_token, raw_refresh


@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db)):
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    await db.flush()  # populate user.id before it's needed for the session row

    access_token, refresh_token = await _issue_session(db, user.id)
    _set_cookies(response, access_token, refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    access_token, refresh_token = await _issue_session(db, user.id)
    _set_cookies(response, access_token, refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw_refresh = request.cookies.get(_REFRESH_COOKIE)
    if not raw_refresh:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    hashed = hash_refresh_token(raw_refresh)
    session = await db.scalar(select(SessionModel).where(SessionModel.refresh_token_hash == hashed))
    if session is None or session.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    # Rotate in place: overwrite this row's token material instead of
    # inserting a new row. A refresh token replayed after rotation (e.g. a
    # stolen cookie used a second time) immediately fails the hash lookup.
    access_token = create_access_token(session.user_id)
    new_raw_refresh, new_hashed_refresh = generate_refresh_token()
    session.refresh_token_hash = new_hashed_refresh
    session.expires_at = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_ttl_days)
    await db.commit()

    _set_cookies(response, access_token, new_raw_refresh)
    return TokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw_refresh = request.cookies.get(_REFRESH_COOKIE)
    if raw_refresh:
        hashed = hash_refresh_token(raw_refresh)
        session = await db.scalar(select(SessionModel).where(SessionModel.refresh_token_hash == hashed))
        if session is not None:
            await db.delete(session)
            await db.commit()

    response.delete_cookie(_ACCESS_COOKIE)
    response.delete_cookie(_REFRESH_COOKIE, path="/auth/refresh")
