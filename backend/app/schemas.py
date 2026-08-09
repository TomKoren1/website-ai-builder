import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProjectCreate(BaseModel):
    name: str


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    git_repo_path: str
    created_at: datetime


class ApiKeyCreate(BaseModel):
    provider: str
    api_key: str


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    provider: str
    display_hint: str
    created_at: datetime
    last_used_at: datetime | None


class DomainCreate(BaseModel):
    project_id: uuid.UUID
    domain_name: str
    s3_bucket_name: str


class DomainOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    domain_name: str
    s3_bucket_name: str
    verified: bool
    created_at: datetime


class ChatRequest(BaseModel):
    provider: str  # "anthropic" | "openai" — must match a stored api_keys.provider
    message: str


class FileChange(BaseModel):
    path: str
    content: str


class ChatResponse(BaseModel):
    reply: str
    proposed_files: list[FileChange]


class PushRequest(BaseModel):
    files: list[FileChange]
    commit_message: str = "Update site"


class DeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    git_commit_sha: str
    status: str
    created_at: datetime
    deployed_at: datetime | None
