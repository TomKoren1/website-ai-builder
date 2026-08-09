import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Every datetime column must be explicitly timezone-aware (TIMESTAMPTZ), not
# SQLAlchemy's default plain DateTime (TIMESTAMP WITHOUT TIME ZONE). App code
# uses datetime.now(timezone.utc) everywhere; asyncpg rejects a tz-aware
# Python datetime against a tz-naive column outright rather than converting
# it, so this isn't optional.
_TZ = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    password_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=func.now())


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Hashed, never the raw refresh token — same principle as password storage.
    # A stolen DB row alone can't be replayed as a refresh token.
    refresh_token_hash: Mapped[str]
    expires_at: Mapped[datetime] = mapped_column(_TZ)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=func.now())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str]
    git_repo_path: Mapped[str]  # e.g. "alice/my-site" — owner/repo on the Gitea instance
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=func.now())


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    domain_name: Mapped[str] = mapped_column(unique=True, index=True)
    s3_bucket_name: Mapped[str]
    verified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_api_keys_user_provider"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str]  # "anthropic" | "openai" — matches app.llm.registry keys
    # Non-sensitive display fragment (e.g. "sk-a...ab12"), computed once at
    # creation time from the plaintext before it's discarded. Without this,
    # a later GET could never show a masked preview — we never store
    # plaintext, so there'd be nothing left to mask.
    display_hint: Mapped[str]
    # Envelope encryption (see app/crypto.py): ciphertext is the API key
    # encrypted with a per-row DEK (AES-256-GCM); encrypted_dek is that DEK
    # wrapped by the KMS CMK. Plaintext is never stored, ever in memory
    # longer than a single LLM call.
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    encrypted_dek: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=func.now())

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str]  # "user" | "assistant"
    content: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    git_commit_sha: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")  # pending | success | failed
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=func.now())
    deployed_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)
