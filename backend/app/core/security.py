from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import SecretStr

PASSWORD_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)
JWT_ALGORITHM = "HS256"
MINIMUM_TOKEN_SECRET_LENGTH = 32


class SecurityConfigurationError(RuntimeError):
    pass


class InvalidAccessTokenError(ValueError):
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


def require_token_secret(secret: SecretStr | None) -> str:
    if secret is None:
        raise SecurityConfigurationError(
            "Authentication token configuration is unavailable."
        )

    value = secret.get_secret_value()
    if len(value.encode("utf-8")) < MINIMUM_TOKEN_SECRET_LENGTH:
        raise SecurityConfigurationError(
            "Authentication token configuration is unavailable."
        )
    return value


def create_access_token(
    *,
    subject: str,
    role: str,
    secret: str,
    expire_minutes: int,
) -> str:
    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=expire_minutes),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "role", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidAccessTokenError("Invalid access token.") from exc

    if not isinstance(payload.get("sub"), str):
        raise InvalidAccessTokenError("Invalid access token.")
    if not isinstance(payload.get("role"), str):
        raise InvalidAccessTokenError("Invalid access token.")
    return payload
