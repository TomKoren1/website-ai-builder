from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Argon2id (the library's default) over bcrypt/passlib: winner of the
# Password Hashing Competition, no 72-byte input truncation footgun,
# and passlib's bcrypt backend has had recurring maintenance issues.
_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, plain)
        return True
    except VerifyMismatchError:
        return False
