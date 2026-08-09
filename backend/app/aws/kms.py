import boto3

from app.aws.sts import get_temporary_credentials
from app.config import get_settings

settings = get_settings()


def _kms_client():
    creds = get_temporary_credentials()
    return boto3.client(
        "kms",
        endpoint_url=settings.aws_endpoint_url,
        region_name=settings.aws_region,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


def encrypt_dek(plaintext_dek: bytes) -> bytes:
    response = _kms_client().encrypt(KeyId=settings.kms_key_alias, Plaintext=plaintext_dek)
    return response["CiphertextBlob"]


def decrypt_dek(encrypted_dek: bytes) -> bytes:
    # KeyId is technically optional on Decrypt (AWS infers it from the
    # ciphertext's own metadata) but passing it anyway is the recommended
    # practice — it makes the call fail loudly if the ciphertext was ever
    # encrypted under a different key than expected, instead of silently
    # decrypting with whatever key the blob happens to reference.
    response = _kms_client().decrypt(CiphertextBlob=encrypted_dek, KeyId=settings.kms_key_alias)
    return response["Plaintext"]
