from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.security import (
    SecurityConfigurationError,
    create_access_token,
    hash_password,
    require_token_secret,
    verify_password,
)
from ..models.user import User
from ..repositories.operation_logs import create_operation_log
from ..repositories.users import get_user_by_username, update_last_login


class InvalidCredentialsError(ValueError):
    pass


@dataclass(frozen=True)
class AuditContext:
    request_id: str
    ip_address: str | None
    user_agent: str | None


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    user: User


def login(
    db: Session,
    *,
    username: str,
    password: str,
    settings: Settings,
    audit: AuditContext,
) -> LoginResult:
    user = get_user_by_username(db, username)
    password_matches = False

    if user is None:
        hash_password(password)
    else:
        password_matches = verify_password(password, user.password_hash)

    if user is None or not password_matches or not user.is_active:
        create_operation_log(
            db,
            actor_type="anonymous",
            actor_id="anonymous",
            action="auth.login",
            target_type="session",
            target_id="current",
            result="failure",
            error_code="invalid_credentials",
            request_id=audit.request_id,
            ip_address=audit.ip_address,
            user_agent=audit.user_agent,
            details={"outcome": "invalid_credentials"},
        )
        db.commit()
        raise InvalidCredentialsError("Invalid username or password.")

    try:
        token_secret = require_token_secret(settings.auth_token_secret)
        access_token = create_access_token(
            subject=str(user.id),
            role=user.role,
            secret=token_secret,
            expire_minutes=settings.auth_token_expire_minutes,
        )
    except SecurityConfigurationError:
        create_operation_log(
            db,
            actor_type="user",
            actor_id=str(user.id),
            action="auth.login",
            target_type="session",
            target_id="current",
            result="failure",
            error_code="authentication_unavailable",
            request_id=audit.request_id,
            ip_address=audit.ip_address,
            user_agent=audit.user_agent,
            details={"outcome": "authentication_unavailable"},
        )
        db.commit()
        raise

    logged_in_at = datetime.now(timezone.utc)
    update_last_login(db, user, logged_in_at)
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(user.id),
        action="auth.login",
        target_type="user",
        target_id=str(user.id),
        result="success",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={"outcome": "authenticated", "role": user.role},
    )
    db.commit()
    return LoginResult(access_token=access_token, user=user)


def logout(db: Session, *, user: User, audit: AuditContext) -> None:
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(user.id),
        action="auth.logout",
        target_type="session",
        target_id=str(user.id),
        result="success",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={"outcome": "stateless_logout"},
    )
    db.commit()
