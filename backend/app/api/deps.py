from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.security import (
    InvalidAccessTokenError,
    SecurityConfigurationError,
    decode_access_token,
    require_token_secret,
)
from ..db.session import get_db
from ..models.user import User
from ..repositories.users import get_user_by_id
from ..services.auth_service import AuditContext

bearer_scheme = HTTPBearer(auto_error=False)
SENSITIVE_HEADER_MARKERS = (
    "bearer",
    "token",
    "secret",
    "password",
    "authorization",
    "api-key",
)


def _safe_header(value: str | None, max_length: int) -> str | None:
    if value is None or len(value) > max_length:
        return None
    lowered = value.lower()
    if any(marker in lowered for marker in SENSITIVE_HEADER_MARKERS):
        return None
    return value


def get_audit_context(request: Request) -> AuditContext:
    request_id = _safe_header(request.headers.get("x-request-id"), 128)
    if request_id is None:
        request_id = str(uuid4())

    ip_address = request.client.host if request.client is not None else None
    if ip_address is not None:
        ip_address = ip_address[:45]

    return AuditContext(
        request_id=request_id,
        ip_address=ip_address,
        user_agent=_safe_header(request.headers.get("user-agent"), 1000),
    )


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()

    try:
        secret = require_token_secret(settings.auth_token_secret)
        payload = decode_access_token(credentials.credentials, secret)
        user_id = int(payload["sub"])
    except (
        InvalidAccessTokenError,
        SecurityConfigurationError,
        TypeError,
        ValueError,
    ):
        raise unauthorized() from None

    user = get_user_by_id(db, user_id)
    if (
        user is None
        or not user.is_active
        or user.role != "owner"
        or payload["role"] != user.role
    ):
        raise unauthorized()
    return user
