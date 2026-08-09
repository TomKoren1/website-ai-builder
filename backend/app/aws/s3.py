import boto3
from botocore.exceptions import ClientError

from app.aws.sts import get_temporary_credentials
from app.config import get_settings

settings = get_settings()


def _s3_client():
    # Uses orchestrator-role's temporary credentials (via sts.py) — the same
    # assume-role pattern as kms.py. orchestrator-role only grants
    # s3:CreateBucket/ListBucket on the "site-*" prefix (infra/terraform/
    # main.tf) — it can never write or read object content, only create the
    # bucket itself. Actual file writes are ci-deploy-role's job, reads are
    # reverse-proxy-role's — see those in main.tf for why.
    creds = get_temporary_credentials()
    return boto3.client(
        "s3",
        endpoint_url=settings.aws_endpoint_url,
        region_name=settings.aws_region,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


def ensure_bucket_exists(bucket_name: str) -> None:
    """Idempotent: a project's first domain creates the bucket; later domains
    on the same project (if that's ever supported) hit the "already owned by
    you" case and no-op rather than erroring."""
    client = _s3_client()
    try:
        client.head_bucket(Bucket=bucket_name)
        return  # already exists
    except ClientError:
        pass  # head_bucket 404s (or 403s under LocalStack) when it doesn't exist yet — fall through to create

    try:
        client.create_bucket(Bucket=bucket_name)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "BucketAlreadyOwnedByYou":
            raise
