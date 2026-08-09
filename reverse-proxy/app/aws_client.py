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


# Same assume-role pattern as backend/app/aws/sts.py — this service's own
# long-lived credentials (reverse-proxy-app) are used for exactly one
# thing, assuming reverse-proxy-role, which grants only s3:GetObject/
# ListBucket on the "site-*" prefix (infra/terraform/main.tf). Duplicated
# rather than imported from the backend package deliberately: this is a
# genuinely separate deployable with its own credentials — sharing a
# library here would mean pulling in the backend's dependency tree for two
# functions' worth of code.
_cache: TemporaryCredentials | None = None
_lock = Lock()


def _sts_client():
    return boto3.client(
        "sts",
        endpoint_url=settings.aws_endpoint_url,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_reverse_proxy_app_access_key_id,
        aws_secret_access_key=settings.aws_reverse_proxy_app_secret_access_key,
    )


def get_temporary_credentials() -> TemporaryCredentials:
    global _cache

    with _lock:
        if _cache is not None and _cache["Expiration"] > datetime.now(timezone.utc) + timedelta(minutes=2):
            return _cache

        response = _sts_client().assume_role(
            RoleArn=settings.aws_reverse_proxy_role_arn,
            RoleSessionName="reverse-proxy",
        )
        creds = response["Credentials"]
        _cache = TemporaryCredentials(
            AccessKeyId=creds["AccessKeyId"],
            SecretAccessKey=creds["SecretAccessKey"],
            SessionToken=creds["SessionToken"],
            Expiration=creds["Expiration"],
        )
        return _cache


def s3_client():
    creds = get_temporary_credentials()
    return boto3.client(
        "s3",
        endpoint_url=settings.aws_endpoint_url,
        region_name=settings.aws_region,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )
