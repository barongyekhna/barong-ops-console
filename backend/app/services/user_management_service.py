from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.security import hash_password
from ..models.user import User
from ..repositories.auth_sessions import invalidate_active_sessions_for_user
from ..repositories.operation_logs import create_operation_log
from ..repositories.organizations import get_organization
from ..repositories.users import (
    create_user as create_user_record,
    get_user_by_id,
    get_user_by_username,
    list_users as list_user_records,
    update_password_hash,
    update_user as update_user_record,
)
from ..schemas.user import (
    DEFAULT_INITIAL_PASSWORD,
    UserCreate,
    UserUpdate,
    initial_must_change_password_for_role,
    validate_user_management_role,
)
from .auth_service import AuditContext


class UserManagementError(ValueError):
    pass


class DuplicateUsernameError(UserManagementError):
    pass


class ManagedUserNotFoundError(UserManagementError):
    pass


class OwnerRoleNotAllowedError(UserManagementError):
    pass


class UserOrganizationNotFoundError(UserManagementError):
    pass


class SelfDisableNotAllowedError(UserManagementError):
    pass


class SelfPasswordResetNotAllowedError(UserManagementError):
    pass


@dataclass(frozen=True)
class UserListResult:
    items: list[User]
    count: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log_user_operation(
    db: Session,
    *,
    actor: User,
    action: str,
    target: User,
    audit: AuditContext,
    details: dict[str, object] | None = None,
) -> None:
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(actor.id),
        action=action,
        target_type="user",
        target_id=str(target.id),
        result="success",
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details=details,
    )


def list_users(
    db: Session,
    *,
    limit: int,
    offset: int,
) -> UserListResult:
    items = list_user_records(db, limit=limit, offset=offset)
    return UserListResult(items=items, count=len(items))


def get_managed_user(db: Session, user_id: int) -> User:
    user = get_user_by_id(db, user_id)
    if user is None:
        raise ManagedUserNotFoundError("User not found.")
    return user


def create_managed_user(
    db: Session,
    *,
    payload: UserCreate,
    actor: User,
    audit: AuditContext,
) -> User:
    try:
        role = validate_user_management_role(payload.role)
    except ValueError as exc:
        raise OwnerRoleNotAllowedError(str(exc)) from None

    username = payload.username.strip()
    if get_user_by_username(db, username) is not None:
        raise DuplicateUsernameError("Username already exists.")
    organization_id = payload.organization_id
    job_title = payload.job_title
    if role == "owner":
        organization_id = None
        job_title = None
    elif (
        organization_id is None
        or get_organization(db, organization_id) is None
    ):
        raise UserOrganizationNotFoundError("Organization not found.")

    try:
        user = create_user_record(
            db,
            username=username,
            password_hash=hash_password(DEFAULT_INITIAL_PASSWORD),
            role=role,
            job_title=job_title,
            organization_id=organization_id,
            must_change_password=initial_must_change_password_for_role(role),
            is_active=payload.is_active,
        )
        _log_user_operation(
            db,
            actor=actor,
            action="user.create",
            target=user,
            audit=audit,
            details={
                "username": user.username,
                "role": user.role,
                "job_title": user.job_title,
                "organization_id": user.organization_id,
                "must_change_password": user.must_change_password,
                "is_active": user.is_active,
            },
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateUsernameError("Username already exists.") from None
    except ValueError:
        db.rollback()
        raise

    db.refresh(user)
    return user


def update_managed_user(
    db: Session,
    *,
    user_id: int,
    payload: UserUpdate,
    actor: User,
    audit: AuditContext,
) -> User:
    user = get_managed_user(db, user_id)
    role = None
    if payload.role is not None:
        try:
            role = validate_user_management_role(payload.role)
        except ValueError as exc:
            raise OwnerRoleNotAllowedError(str(exc)) from None
    if user.id == actor.id and payload.is_active is False:
        raise SelfDisableNotAllowedError("Current owner cannot be disabled.")

    before = {"role": user.role, "is_active": user.is_active}
    user = update_user_record(
        db,
        user,
        role=role,
        is_active=payload.is_active,
    )
    after = {"role": user.role, "is_active": user.is_active}
    _log_user_operation(
        db,
        actor=actor,
        action="user.update",
        target=user,
        audit=audit,
        details={"before": before, "after": after},
    )
    db.commit()
    db.refresh(user)
    return user


def reset_managed_user_password(
    db: Session,
    *,
    user_id: int,
    new_password: str,
    actor: User,
    audit: AuditContext,
) -> User:
    user = get_managed_user(db, user_id)
    if user.id == actor.id:
        raise SelfPasswordResetNotAllowedError(
            "Current owner password reset is not available here."
        )

    user = update_password_hash(
        db,
        user,
        hash_password(new_password),
        must_change_password=True,
    )
    invalidated_session_count = invalidate_active_sessions_for_user(
        db,
        user_id=user.id,
        invalidated_at=_now(),
        reason="password_reset",
    )
    _log_user_operation(
        db,
        actor=actor,
        action="user.reset_password",
        target=user,
        audit=audit,
        details={
            "username": user.username,
            "role": user.role,
            "invalidated_session_count": invalidated_session_count,
        },
    )
    db.commit()
    db.refresh(user)
    return user


def disable_managed_user(
    db: Session,
    *,
    user_id: int,
    actor: User,
    audit: AuditContext,
) -> User:
    user = get_managed_user(db, user_id)
    if user.id == actor.id:
        raise SelfDisableNotAllowedError("Current owner cannot be disabled.")

    user = update_user_record(db, user, is_active=False)
    _log_user_operation(
        db,
        actor=actor,
        action="user.disable",
        target=user,
        audit=audit,
        details={"username": user.username, "role": user.role},
    )
    db.commit()
    db.refresh(user)
    return user


def enable_managed_user(
    db: Session,
    *,
    user_id: int,
    actor: User,
    audit: AuditContext,
) -> User:
    user = get_managed_user(db, user_id)
    user = update_user_record(db, user, is_active=True)
    _log_user_operation(
        db,
        actor=actor,
        action="user.enable",
        target=user,
        audit=audit,
        details={"username": user.username, "role": user.role},
    )
    db.commit()
    db.refresh(user)
    return user
