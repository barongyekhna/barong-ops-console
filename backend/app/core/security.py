import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

PASSWORD_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)
SESSION_ID_BYTES = 32


class InvalidSessionIdError(ValueError):
    pass


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password must not be empty.")
    if len(password.encode("utf-8")) > 1024:
        raise ValueError("Password is too long.")
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        return False


def generate_session_id() -> str:
    return secrets.token_urlsafe(SESSION_ID_BYTES)


def hash_session_id(session_id: str) -> str:
    if not session_id or len(session_id) > 512:
        raise InvalidSessionIdError("Invalid session id.")
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()
