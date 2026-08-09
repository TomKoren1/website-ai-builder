import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.aws.kms import decrypt_dek, encrypt_dek


def encrypt_api_key(plaintext: str) -> tuple[bytes, bytes, bytes]:
    """Envelope-encrypts an API key. Returns (ciphertext, encrypted_dek, nonce).

    A fresh DEK per key (not a shared one) means compromising one row's
    plaintext never helps decrypt any other row — each is independently
    wrapped by KMS.
    """
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode(), None)
    wrapped_dek = encrypt_dek(dek)
    return ciphertext, wrapped_dek, nonce


def decrypt_api_key(ciphertext: bytes, encrypted_dek: bytes, nonce: bytes) -> str:
    """Decrypts back to plaintext. Caller must use it immediately and let
    it go out of scope — never cache or log the return value."""
    dek = decrypt_dek(encrypted_dek)
    plaintext = AESGCM(dek).decrypt(nonce, ciphertext, None)
    return plaintext.decode()
