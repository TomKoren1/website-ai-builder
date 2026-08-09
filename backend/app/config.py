from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str

    # "local" disables the cookie Secure flag (browsers refuse to store
    # Secure cookies over plain HTTP, which `next dev` uses) — never set
    # this to anything but "local" outside your own machine.
    environment: str = "local"
    frontend_origin: str = "http://localhost:3000"

    jwt_secret: str
    jwt_access_token_ttl_minutes: int = 15
    jwt_refresh_token_ttl_days: int = 30

    aws_endpoint_url: str
    aws_region: str = "us-east-1"
    aws_orchestrator_app_access_key_id: str
    aws_orchestrator_app_secret_access_key: str
    aws_orchestrator_role_arn: str
    kms_key_alias: str

    gitea_url: str
    gitea_admin_username: str
    gitea_admin_token: str


@lru_cache
def get_settings() -> Settings:
    # Cached: env vars don't change mid-process, and this avoids re-parsing
    # the .env file on every request that depends on settings.
    return Settings()
