from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Same Postgres instance/database the backend uses — this service reads
    # the `domains` table directly rather than going through the backend
    # API, since it's a hot path (every visitor request) and the lookup is
    # trivial. Reuses the backend's `app` DB user rather than a dedicated
    # read-only role for now — a real scoping gap (this service could,
    # credential-wise, write to any table, though the code never does) —
    # see infra/PHASE4-RUNBOOK-B.md for why that's a known follow-up, not
    # done in this pass.
    database_url: str

    aws_endpoint_url: str
    aws_region: str = "us-east-1"
    aws_reverse_proxy_app_access_key_id: str
    aws_reverse_proxy_app_secret_access_key: str
    aws_reverse_proxy_role_arn: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
