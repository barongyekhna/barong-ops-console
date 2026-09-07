from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.security import hash_password
from ..core.roles import is_org_admin_like_role, is_owner_role, normalize_role
from ..models.user import User
from ..modules.c19.identity_sync_service import (
    sync_profile_for_user,
    sync_user_identity,
)
from ..repositories.auth_sessions import invalidate_active_sessions_for_user
from ..repositories.operation_logs import create_operation_log
from ..repositories.organizations import get_organization
from ..repositories.users import (
    count_users as count_user_records,
    create_user as create_user_record,
    get_user_by_id,
    get_user_by_username,
    list_users as list_user_records,
    update_password_hash,
    update_user as update_user_record,
)
from ..schemas.user import (
    BotCreate,
    UserCreate,
    UserUpdate,
    generate_initial_password,
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


class UserManagementPermissionDeniedError(PermissionError):
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


def _actor_org_id(actor: User) -> str | None:
    organization_id = actor.organization_id
    if organization_id is None:
        return None
    organization_id = organization_id.strip()
    return organization_id or None


def _ensure_actor_can_manage_user(actor: User, target: User) -> None:
    if is_owner_role(actor.role):
        return
    if not is_org_admin_like_role(actor.role):
        raise UserManagementPermissionDeniedError(
            "Owner, super admin, or admin role required."
        )
    actor_org_id = _actor_org_id(actor)
    if actor_org_id is None:
        raise UserManagementPermissionDeniedError(
            "Organization admin context is required."
        )
    if normalize_role(target.role) in {"owner", "super_admin"}:
        raise UserManagementPermissionDeniedError(
            "Organization admin cannot manage owner or super admin accounts."
        )
    if target.organization_id != actor_org_id:
        raise UserManagementPermissionDeniedError(
            "Organization admin can only manage users in their organization."
        )


def _ensure_actor_can_create_user(
    actor: User,
    *,
    role: str,
    organization_id: str | None,
) -> str | None:
    if is_owner_role(actor.role):
        return organization_id
    if not is_org_admin_like_role(actor.role):
        raise UserManagementPermissionDeniedError(
            "Owner, super admin, or admin role required."
        )
    actor_org_id = _actor_org_id(actor)
    if actor_org_id is None:
        raise UserManagementPermissionDeniedError(
            "Organization admin context is required."
        )
    if role in {"owner", "super_admin"}:
        raise UserManagementPermissionDeniedError(
            "Organization admin cannot create owner or super admin accounts."
        )
    if organization_id is not None and organization_id != actor_org_id:
        raise UserManagementPermissionDeniedError(
            "Organization admin can only create users in their organization."
        )
    return actor_org_id


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
    organization_id: str | None = None,
    role: str | None = None,
) -> UserListResult:
    items = list_user_records(
        db,
        limit=limit,
        offset=offset,
        organization_id=organization_id,
        role=role,
    )
    count = count_user_records(
        db,
        organization_id=organization_id,
        role=role,
    )
    return UserListResult(items=items, count=count)


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
) -> tuple[User, str]:
    try:
        role = validate_user_management_role(payload.role)
    except ValueError as exc:
        raise OwnerRoleNotAllowedError(str(exc)) from None

    username = payload.username.strip()
    if get_user_by_username(db, username) is not None:
        raise DuplicateUsernameError("Username already exists.")
    organization_id = _ensure_actor_can_create_user(
        actor,
        role=role,
        organization_id=payload.organization_id,
    )
    job_title = payload.job_title
    if role == "owner":
        organization_id = None
        job_title = None
    elif (
        organization_id is None
        or get_organization(db, organization_id) is None
    ):
        raise UserOrganizationNotFoundError("Organization not found.")

    # Random one-time initial password instead of the guessable "123456";
    # plaintext is returned to the creator once and never stored in cleartext.
    initial_password = generate_initial_password()
    try:
        user = create_user_record(
            db,
            username=username,
            password_hash=hash_password(initial_password),
            role=role,
            job_title=job_title,
            organization_id=organization_id,
            must_change_password=initial_must_change_password_for_role(role),
            is_active=payload.is_active,
        )
        sync_profile_for_user(db, user=user)
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
    return user, initial_password


def update_managed_user(
    db: Session,
    *,
    user_id: int,
    payload: UserUpdate,
    actor: User,
    audit: AuditContext,
) -> User:
    user = get_managed_user(db, user_id)
    _ensure_actor_can_manage_user(actor, user)
    role = None
    if payload.role is not None:
        try:
            role = validate_user_management_role(payload.role)
        except ValueError as exc:
            raise OwnerRoleNotAllowedError(str(exc)) from None
        if not is_owner_role(actor.role) and role in {"owner", "super_admin"}:
            raise UserManagementPermissionDeniedError(
                "Super admin cannot assign owner or super admin roles."
            )
    if user.id == actor.id and payload.is_active is False:
        raise SelfDisableNotAllowedError("Current owner cannot be disabled.")

    must_change_password = (
        initial_must_change_password_for_role(role)
        if role is not None
        else None
    )
    before = {
        "role": user.role,
        "must_change_password": user.must_change_password,
        "is_active": user.is_active,
    }
    user = update_user_record(
        db,
        user,
        role=role,
        must_change_password=must_change_password,
        is_active=payload.is_active,
    )
    if payload.is_active is not None:
        sync_user_identity(db, user=user)
    after = {
        "role": user.role,
        "must_change_password": user.must_change_password,
        "is_active": user.is_active,
    }
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
    _ensure_actor_can_manage_user(actor, user)
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
    _ensure_actor_can_manage_user(actor, user)
    if user.id == actor.id:
        raise SelfDisableNotAllowedError("Current owner cannot be disabled.")

    user = update_user_record(db, user, is_active=False)
    sync_user_identity(db, user=user)
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
    _ensure_actor_can_manage_user(actor, user)
    user = update_user_record(db, user, is_active=True)
    sync_user_identity(db, user=user)
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


# ---------------------------------------------------------------- 机器人注册 / 账号清理
#
# 2026-08-22 拍板:以后的机器人必须在用户管理里注册(带清晰的机器人标记和所属组织),
# 不再靠各自的脚本偷偷建号。注册只做"身份":用户行 + C19 资料 + 组织成员关系;
# 每个数字员工的职责/红灯清单仍由各自模块的 agent_registry 登记。


class BotOperationNotAllowedError(UserManagementError):
    pass


class UserPurgeBlockedError(UserManagementError):
    pass


def create_bot_user(
    db: Session,
    *,
    payload: BotCreate,
    actor: User,
    audit: AuditContext,
) -> User:
    """注册一个数字员工:viewer 角色 + is_bot + 挂一个组织 + C19 显示名/简介。

    零权限码——机器人能干什么由它自己的 worker 以说话人身份过各模块的门,
    不在这里授权。只有 owner 能注册。
    """
    from ..models.c19 import C19ProfileRecord
    from ..models.org_membership import OrgMembershipRecord
    from ..schemas.org_membership import generate_membership_id
    from sqlalchemy import select

    if not is_owner_role(actor.role):
        raise UserManagementPermissionDeniedError("Only the owner can register bots.")
    username = payload.username.strip()
    if get_user_by_username(db, username) is not None:
        raise DuplicateUsernameError("Username already exists.")
    if get_organization(db, payload.organization_id) is None:
        raise UserOrganizationNotFoundError("Organization not found.")
    try:
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise UserManagementError(f"Password rejected: {exc}") from None

    try:
        user = create_user_record(
            db,
            username=username,
            password_hash=password_hash,
            role="viewer",
            job_title=payload.job_title,
            organization_id=payload.organization_id,
            must_change_password=False,
            is_active=True,
        )
        user.is_bot = True
        db.add(user)
        db.flush()
        sync_profile_for_user(db, user=user)
        profile = db.get(C19ProfileRecord, user.id)
        if profile is not None:
            profile.display_name = payload.display_name.strip()
            profile.bio = (payload.bio or "").strip() or None
            db.add(profile)
        existing = db.scalar(
            select(OrgMembershipRecord).where(
                OrgMembershipRecord.user_id == str(user.id),
                OrgMembershipRecord.org_id == payload.organization_id,
            )
        )
        if existing is None:
            db.add(
                OrgMembershipRecord(
                    membership_id=generate_membership_id(),
                    user_id=str(user.id),
                    org_id=payload.organization_id,
                    role="member",
                    status="active",
                )
            )
        _log_user_operation(
            db,
            actor=actor,
            action="user.bot.register",
            target=user,
            audit=audit,
            details={
                "username": user.username,
                "display_name": payload.display_name,
                "job_title": user.job_title,
                "organization_id": user.organization_id,
            },
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateUsernameError("Username already exists.") from None
    db.refresh(user)
    return user


def purge_managed_user(
    db: Session,
    *,
    user_id: int,
    actor: User,
    audit: AuditContext,
) -> dict[str, object]:
    """彻底删除一个账号。只删:已停用、非 owner、非自己、没有业务记录引用的账号。

    有审批/评审/客服回信/自动化任务引用的账号只能停用不能删——那些记录要能
    追溯到人。C19 会话历史保留(会话行不删,成员关系删)。
    """
    from sqlalchemy import delete, select, func
    from ..models.approval import ApprovalDecisionRecord, ApprovalRequestRecord
    from ..models.auth_session import AuthSession
    from ..models.c19 import C19ConversationMemberRecord
    from ..models.error import SystemError
    from ..models.job import AutomationJob
    from ..models.org_membership import OrgMembershipRecord
    from ..models.permission import UserPermissionAssignment
    from ..models.review import ReviewItem
    from .data_isolation import without_org_data_isolation

    if not is_owner_role(actor.role):
        raise UserManagementPermissionDeniedError("Only the owner can delete accounts.")
    user = get_managed_user(db, user_id)
    if user.id == actor.id:
        raise BotOperationNotAllowedError("Cannot delete yourself.")
    if is_owner_role(user.role):
        raise BotOperationNotAllowedError("Owner accounts cannot be deleted.")
    if user.is_active:
        raise BotOperationNotAllowedError("Disable the account first, then delete it.")

    with without_org_data_isolation():
        refs: dict[str, int] = {}
        checks = [
            ("approval_requests", select(func.count()).select_from(ApprovalRequestRecord).where(
                (ApprovalRequestRecord.requester_id == user.id) | (ApprovalRequestRecord.reviewer_id == user.id))),
            ("approval_decisions", select(func.count()).select_from(ApprovalDecisionRecord).where(ApprovalDecisionRecord.actor_id == user.id)),
            ("review_items", select(func.count()).select_from(ReviewItem).where(
                (ReviewItem.requested_by == user.id) | (ReviewItem.assigned_to == user.id) | (ReviewItem.decided_by == user.id))),
            ("automation_jobs", select(func.count()).select_from(AutomationJob).where(AutomationJob.requested_by_user_id == user.id)),
            ("system_errors", select(func.count()).select_from(SystemError).where(SystemError.acknowledged_by == user.id)),
            ("granted_permissions", select(func.count()).select_from(UserPermissionAssignment).where(UserPermissionAssignment.granted_by_user_id == user.id)),
        ]
        for name, stmt in checks:
            count = int(db.scalar(stmt) or 0)
            if count:
                refs[name] = count
        if refs:
            raise UserPurgeBlockedError(
                "Account has business records and can only stay disabled: "
                + ", ".join(f"{k}={v}" for k, v in refs.items())
            )

        removed = {
            "conversation_memberships": db.execute(
                delete(C19ConversationMemberRecord).where(C19ConversationMemberRecord.user_id == user.id)
            ).rowcount,
            "org_memberships": db.execute(
                delete(OrgMembershipRecord).where(OrgMembershipRecord.user_id == str(user.id))
            ).rowcount,
            "auth_sessions": db.execute(delete(AuthSession).where(AuthSession.user_id == user.id)).rowcount,
            "permission_assignments": db.execute(
                delete(UserPermissionAssignment).where(UserPermissionAssignment.user_id == user.id)
            ).rowcount,
        }
        details = {"username": user.username, "role": user.role, "is_bot": bool(user.is_bot), "removed": removed}
        _log_user_operation(db, actor=actor, action="user.purge", target=user, audit=audit, details=details)
        db.delete(user)  # c19_profiles 及其下游(affiliations/friend_requests/blocks)由 FK CASCADE 带走
        db.commit()
    return {"user_id": user_id, **details}
