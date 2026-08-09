from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import TypedDict

import boto3

from app.config import get_settings

settings = get_settings()


class TemporaryCredentials(TypedDict):
    AccessKeyId: str
    SecretAccessKey: str
    SessionToken: str
    Expiration: datetime


_cache: TemporaryCredentials | None = None
_lock = Lock()


def _sts_client():
    # The backend's only long-lived credentials are the orchestrator-app
    # user's own keys, and this is the ONLY thing they're ever used for —
    # assuming the narrowly-scoped orchestrator-role (see infra/terraform/
    # main.tf). Every actual KMS/S3 call uses the short-lived credentials
    # that come back from that assume-role, never these directly.
    return boto3.client(
        "sts",
        endpoint_url=settings.aws_endpoint_url,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_orchestrator_app_access_key_id,
        aws_secret_access_key=settings.aws_orchestrator_app_secret_access_key,
    )


def get_temporary_credentials() -> TemporaryCredentials:
    """Returns cached temp credentials, refreshing via STS shortly before expiry."""
    global _cache

    with _lock:
        if _cache is not None and _cache["Expiration"] > datetime.now(timezone.utc) + timedelta(minutes=2):
            return _cache

        response = _sts_client().assume_role(
            RoleArn=settings.aws_orchestrator_role_arn,
            RoleSessionName="backend-orchestrator",
        )
        creds = response["Credentials"]
        _cache = TemporaryCredentials(
            AccessKeyId=creds["AccessKeyId"],
            SecretAccessKey=creds["SecretAccessKey"],
            SessionToken=creds["SessionToken"],
            Expiration=creds["Expiration"],
        )
        return _cache
