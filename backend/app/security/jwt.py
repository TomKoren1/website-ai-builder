import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings

settings = get_settings()

_ALGORITHM = "HS256"


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Raises jwt.PyJWTError (expired, bad signature, malformed) on failure."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    return uuid.UUID(payload["sub"])


def generate_refresh_token() -> tuple[str, str]:
    """Returns (raw_token_to_give_the_client, hash_to_store_in_db).

    Refresh tokens are high-entropy random strings, not JWTs — there's
    nothing to encode in them, and unlike a JWT they must be checked
    against the DB anyway (to support revocation on logout), so a JWT's
    self-contained-claims property buys nothing here.
    """
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    # SHA-256 (not argon2) deliberately: this token is already 256 bits of
    # random entropy, not a human-guessable password — a fast hash is fine
    # and avoids needless CPU cost on every refresh-token lookup.
    return hashlib.sha256(raw.encode()).hexdigest()
