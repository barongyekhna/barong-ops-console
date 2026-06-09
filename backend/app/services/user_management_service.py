from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.security import hash_password
from ..models.user import User
from ..repositories.operation_logs import create_operation_log
from ..repositories.users import (
    create_user as create_user_record,
    get_user_by_id,
    get_user_by_username,
    list_users as list_user_records,
    update_password_hash,
    update_user as update_user_record,
)
from ..schemas.user import UserCreate, UserUpdate
from .auth_service import AuditContext


class UserManagementError(ValueError):
    pass


class DuplicateUsernameError(UserManagementError):
    pass


class ManagedUserNotFoundError(UserManagementError):
    pass


class OwnerRoleNotAllowedError(UserManagementError):
    pass


class SelfDisableNotAllowedError(UserManagementError):
    pass


class SelfPasswordResetNotAllowedError(UserManagementError):
    pass


@dataclass(frozen=True)
class UserListResult:
    items: list[User]
    count: int


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
    if payload.role == "owner":
        raise OwnerRoleNotAllowedError("Owner role cannot be created here.")

    username = payload.username.strip()
    if get_user_by_username(db, username) is not None:
        raise DuplicateUsernameError("Username already exists.")

    try:
        user = create_user_record(
            db,
            username=username,
            password_hash=hash_password(payload.password.get_secret_value()),
            role=payload.role,
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
    if payload.role == "owner":
        raise OwnerRoleNotAllowedError("Owner role cannot be assigned here.")
    if user.id == actor.id and payload.is_active is False:
        raise SelfDisableNotAllowedError("Current owner cannot be disabled.")

    before = {"role": user.role, "is_active": user.is_active}
    user = update_user_record(
        db,
        user,
        role=payload.role,
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

    user = update_password_hash(db, user, hash_password(new_password))
    _log_user_operation(
        db,
        actor=actor,
        action="user.reset_password",
        target=user,
        audit=audit,
        details={"username": user.username, "role": user.role},
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
