from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.permissions import (
    BASE_PERMISSION_REGISTRY_SEED,
    PermissionDefinition,
    RISK_LEVEL_CRITICAL,
    RISK_LEVEL_HIGH,
    SCOPE_GLOBAL,
    SCOPE_ORGANIZATION,
    validate_permission_definition,
    validate_permission_key,
    validate_scope,
)
from ..core.roles import is_owner_role, is_super_admin_role, normalize_role
from ..models.permission import (
    PermissionRegistry,
    RoleDefaultPermission,
    UserPermissionAssignment,
)
from ..models.user import User
from ..repositories.permissions import (
    disable_assignment as disable_assignment_record,
    disable_retired_permission_registry_entries,
    get_permission as get_permission_record,
    get_user_assignment,
    get_user_assignment_by_id,
    list_enabled_permissions as list_enabled_permission_records,
    list_enabled_user_assignments,
    list_permissions as list_permission_records,
    list_role_default_permissions as list_role_default_permission_records,
    list_user_assignments as list_user_assignment_records,
    save_user_assignment,
    upsert_permission_registry as upsert_permission_registry_records,
    upsert_role_default_permission as upsert_role_default_permission_record,
    upsert_user_assignment,
)
from ..repositories.operation_logs import create_operation_log
from ..schemas.permission import PermissionAssignmentUpdate
from .auth_service import AuditContext
from .permission_decision_engine import PermissionDecisionEngine
from .permission_resolution_cache import (
    PermissionResolutionCache,
    clear_permission_ttl_cache,
    get_permission_request_cache,
)
from .unified_permission_engine import (
    OWNER_PLATFORM_PERMISSION_CATEGORIES,
    UnifiedPermissionRequest,
)


class PermissionServiceError(ValueError):
    pass


class PermissionNotFoundError(PermissionServiceError):
    pass


class PermissionDisabledError(PermissionServiceError):
    pass


class PermissionAssignmentNotFoundError(PermissionServiceError):
    pass


class PermissionUserNotFoundError(PermissionServiceError):
    pass


class PermissionAssignmentDuplicateError(PermissionServiceError):
    pass


class PermissionAssignmentOwnerTargetError(PermissionServiceError):
    pass


class PermissionAssignmentWildcardError(PermissionServiceError):
    pass


class PermissionAssignmentHighRiskConfirmationError(PermissionServiceError):
    pass


class PermissionAssignmentHighRiskReasonError(PermissionServiceError):
    pass


class PermissionAssignmentKeyUpdateNotAllowedError(PermissionServiceError):
    pass


class PermissionAssignmentScopeForbiddenError(PermissionServiceError):
    """Actor is not allowed to manage this target user's permissions."""


def ensure_actor_can_manage_target_permissions(
    actor: User,
    target_user: User,
) -> None:
    """Enforce the assignment authority ladder.

    - Owner: may manage any (non-owner) user's permissions, in any organization.
    - Super admin: may manage only non-owner / non-super-admin members of their
      OWN organization.
    - Anyone else: rejected (the endpoint dependency already gates, this is the
      authoritative backstop so the rule holds even if a caller bypasses it).
    """
    if is_owner_role(actor.role):
        return
    if not is_super_admin_role(actor.role):
        raise PermissionAssignmentScopeForbiddenError(
            "Owner or super admin role is required to manage permissions."
        )
    actor_org = (actor.organization_id or "").strip()
    if not actor_org:
        raise PermissionAssignmentScopeForbiddenError(
            "Super admin organization context is required to manage permissions."
        )
    if normalize_role(target_user.role) in {"owner", "super_admin"}:
        raise PermissionAssignmentScopeForbiddenError(
            "Super admin cannot manage owner or super admin permissions."
        )
    if (target_user.organization_id or "").strip() != actor_org:
        raise PermissionAssignmentScopeForbiddenError(
            "Super admin can only manage permissions for users in their own organization."
        )


HIGH_RISK_CONFIRMATION_TEXT = "CONFIRM_HIGH_RISK_PERMISSION"
PERMISSION_ASSIGNMENT_GRANT_ACTION = "permission.assignment.grant"
PERMISSION_ASSIGNMENT_UPDATE_ACTION = "permission.assignment.update"
PERMISSION_ASSIGNMENT_REVOKE_ACTION = "permission.assignment.revoke"

HIGH_RISK_PERMISSION_KEYS = frozenset(
    {
        "users.manage",
        "permissions.manage",
        "system.settings.manage",
        "settings.manage",
        "system.admin",
        "secrets.manage",
        "release.manage",
        "production.release",
        "production.manage",
        "billing.manage",
    }
)
HIGH_RISK_KEY_MARKERS = (
    "admin",
    "system",
    "release",
    "secret",
    "secrets",
    "production",
    "billing",
)
HIGH_RISK_ADMIN_ACTIONS = frozenset({"manage", "admin", "release"})


@dataclass(frozen=True)
class EffectivePermissionScope:
    permission_key: str
    scope_type: str
    scope_key: str
    expires_at: datetime | None


@dataclass(frozen=True)
class EffectivePermissions:
    user_id: int
    role: str
    is_owner_full_access: bool
    permissions: list[str]
    scoped_permissions: list[EffectivePermissionScope]
    is_platform_owner: bool = False


@dataclass(frozen=True)
class EffectivePermissionAssignment:
    permission_key: str
    scope_type: str
    scope_key: str


@dataclass(frozen=True)
class EffectivePermissionScopeSummary:
    scope_type: str
    scope_key: str
    permission_keys: list[str]


@dataclass(frozen=True)
class CurrentUserPermissionInfo:
    is_owner_full_access: bool
    permission_keys: list[str]
    assignments: list[EffectivePermissionAssignment]
    scope_summary: list[EffectivePermissionScopeSummary]
    is_platform_owner: bool = False


@dataclass(frozen=True)
class PermissionAssignmentView:
    id: UUID
    user_id: int
    permission_key: str
    permission_name: str | None
    description: str | None
    scope_type: str
    scope_id: str
    scope_key: str
    enabled: bool
    is_enabled: bool
    expires_at: datetime | None
    granted_by_user_id: int | None
    created_at: datetime
    updated_at: datetime
    reason: str | None
    risk_level: str | None
    high_risk: bool
    effective: bool


@dataclass(frozen=True)
class PermissionAssignmentListResult:
    user_id: int
    username: str
    role: str
    is_owner_full_access: bool
    owner_full_access_note: str | None
    assignments: list[PermissionAssignmentView]


@dataclass(frozen=True)
class PermissionAssignmentActionResult:
    assignment: PermissionAssignmentView
    operation_id: str


MODULES_ME_PERMISSION_INFO_CACHE_NAMESPACE = "modules_me_permission_info"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(
    expires_at: datetime | None,
    *,
    now: datetime,
) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= now


def _assignment_matches_scope(
    assignment: UserPermissionAssignment,
    *,
    scope_type: str,
    scope_key: str,
) -> bool:
    if assignment.scope_type == SCOPE_GLOBAL and assignment.scope_key == "*":
        return True
    if scope_type == SCOPE_GLOBAL:
        return False
    if assignment.scope_type != scope_type:
        return False
    return assignment.scope_key in {scope_key, "*"}


def _datetime_for_details(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _has_reason(reason: str | None) -> bool:
    return reason is not None and bool(reason.strip())


def _has_high_risk_confirmation(
    *,
    reason: str | None,
    confirm_high_risk: bool,
    confirmation_text: str | None,
) -> bool:
    return (
        _has_reason(reason)
        and confirm_high_risk
        and confirmation_text == HIGH_RISK_CONFIRMATION_TEXT
    )


def _is_assignment_active(
    assignment: UserPermissionAssignment,
    *,
    now: datetime,
) -> bool:
    return assignment.is_enabled and not _is_expired(
        assignment.expires_at,
        now=now,
    )


def _assignment_is_effective(
    assignment: UserPermissionAssignment,
    permission: PermissionRegistry | None,
    *,
    now: datetime,
) -> bool:
    return (
        permission is not None
        and permission.is_enabled
        and assignment.is_enabled
        and not _is_expired(assignment.expires_at, now=now)
    )


def _assignment_values_are_effective(
    *,
    permission: PermissionRegistry | None,
    enabled: bool,
    expires_at: datetime | None,
    now: datetime,
) -> bool:
    return (
        permission is not None
        and permission.is_enabled
        and enabled
        and not _is_expired(expires_at, now=now)
    )


def _is_scope_expanded_or_changed(
    *,
    before_scope_type: str,
    before_scope_key: str,
    after_scope_type: str,
    after_scope_key: str,
) -> bool:
    if (
        before_scope_type == after_scope_type
        and before_scope_key == after_scope_key
    ):
        return False
    if after_scope_type == SCOPE_GLOBAL and before_scope_type != SCOPE_GLOBAL:
        return True
    if after_scope_type != before_scope_type:
        return True
    if after_scope_key == "*" and before_scope_key != "*":
        return True
    return True


def _assignment_state(
    assignment: UserPermissionAssignment | None,
) -> dict[str, object] | None:
    if assignment is None:
        return None
    return {
        "assignment_id": str(assignment.id),
        "user_id": assignment.user_id,
        "permission_key": assignment.permission_key,
        "scope_type": assignment.scope_type,
        "scope_id": assignment.scope_key,
        "scope_key": assignment.scope_key,
        "enabled": assignment.is_enabled,
        "is_enabled": assignment.is_enabled,
        "expires_at": _datetime_for_details(assignment.expires_at),
        "granted_by_user_id": assignment.granted_by_user_id,
        "reason": assignment.reason,
    }


def detect_high_risk_permission(permission: PermissionRegistry) -> bool:
    permission_key = permission.permission_key
    key_parts = set(permission_key.split("."))
    if permission.risk_level in {RISK_LEVEL_HIGH, RISK_LEVEL_CRITICAL}:
        return True
    if permission_key in HIGH_RISK_PERMISSION_KEYS:
        return True
    if any(marker in key_parts for marker in HIGH_RISK_KEY_MARKERS):
        return True
    if any(marker in permission_key for marker in HIGH_RISK_KEY_MARKERS):
        return True
    if (
        permission.category in {"admin", "system"}
        and permission.action in HIGH_RISK_ADMIN_ACTIONS
    ):
        return True
    if permission.module_key in {"admin", "system", "release", "secrets", "production"}:
        return True
    return False


def _build_assignment_view(
    db: Session,
    assignment: UserPermissionAssignment,
    *,
    permission: PermissionRegistry | None = None,
    now: datetime | None = None,
) -> PermissionAssignmentView:
    permission = permission or get_permission_record(
        db,
        assignment.permission_key,
    )
    current_time = now or _utc_now()
    return PermissionAssignmentView(
        id=assignment.id,
        user_id=assignment.user_id,
        permission_key=assignment.permission_key,
        permission_name=permission.label if permission is not None else None,
        description=permission.description if permission is not None else None,
        scope_type=assignment.scope_type,
        scope_id=assignment.scope_key,
        scope_key=assignment.scope_key,
        enabled=assignment.is_enabled,
        is_enabled=assignment.is_enabled,
        expires_at=assignment.expires_at,
        granted_by_user_id=assignment.granted_by_user_id,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
        reason=assignment.reason,
        risk_level=permission.risk_level if permission is not None else None,
        high_risk=(
            detect_high_risk_permission(permission)
            if permission is not None
            else False
        ),
        effective=_assignment_is_effective(
            assignment,
            permission,
            now=current_time,
        ),
    )


def _require_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise PermissionUserNotFoundError("User not found.")
    return user


def _require_enabled_permission(
    db: Session,
    permission_key: str,
) -> PermissionRegistry:
    permission = get_permission(db, permission_key)
    if permission is None:
        raise PermissionNotFoundError("Permission not found.")
    if not permission.is_enabled:
        raise PermissionDisabledError("Permission is disabled.")
    return permission


def validate_permission_key_exists(
    db: Session,
    permission_key: str,
) -> PermissionRegistry:
    if permission_key.strip() == "*":
        raise PermissionAssignmentWildcardError(
            "Wildcard permission assignments are not allowed."
        )
    normalized_key = validate_permission_key(permission_key)
    return _require_enabled_permission(db, normalized_key)


def prevent_duplicate_active_assignment(
    db: Session,
    *,
    user_id: int,
    permission_key: str,
    scope_type: str,
    scope_key: str,
    exclude_assignment_id: UUID | None = None,
) -> UserPermissionAssignment | None:
    existing = get_user_assignment(
        db,
        user_id=user_id,
        permission_key=permission_key,
        scope_type=scope_type,
        scope_key=scope_key,
    )
    if existing is None:
        return None
    if exclude_assignment_id is not None and existing.id == exclude_assignment_id:
        return existing
    if _is_assignment_active(existing, now=_utc_now()):
        raise PermissionAssignmentDuplicateError(
            "Active permission assignment already exists."
        )
    if exclude_assignment_id is not None:
        raise PermissionAssignmentDuplicateError(
            "Permission assignment already exists for that user and scope."
        )
    return existing


def _write_permission_operation_log(
    db: Session,
    *,
    actor: User,
    action: str,
    target_user_id: int,
    assignment_id: UUID | None,
    permission_key: str | None,
    scope_type: str | None,
    scope_key: str | None,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
    reason: str | None,
    risk_level: str | None,
    high_risk: bool,
    result: str,
    audit: AuditContext,
    error_code: str | None = None,
    confirmation_provided: bool = False,
) -> str:
    operation_log = create_operation_log(
        db,
        actor_type="user",
        actor_id=str(actor.id),
        action=action,
        target_type=(
            "user_permission_assignment"
            if assignment_id is not None
            else "user"
        ),
        target_id=str(assignment_id or target_user_id),
        result=result,
        error_code=error_code,
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details={
            "actor_user_id": actor.id,
            "target_user_id": target_user_id,
            "action": action,
            "permission_key": permission_key,
            "assignment_id": str(assignment_id) if assignment_id else None,
            "scope_type": scope_type,
            "scope_id": scope_key,
            "scope_key": scope_key,
            "before": before,
            "after": after,
            "reason": reason,
            "risk_level": risk_level,
            "high_risk": high_risk,
            "requires_confirmation": high_risk,
            "confirmation_provided": confirmation_provided,
            "result": result,
        },
    )
    return operation_log.operation_id


def write_permission_operation_log(
    db: Session,
    *,
    actor: User,
    action: str,
    target_user_id: int,
    assignment_id: UUID | None,
    permission_key: str | None,
    scope_type: str | None,
    scope_key: str | None,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
    reason: str | None,
    risk_level: str | None,
    high_risk: bool,
    result: str,
    audit: AuditContext,
    error_code: str | None = None,
    confirmation_provided: bool = False,
) -> str:
    return _write_permission_operation_log(
        db,
        actor=actor,
        action=action,
        target_user_id=target_user_id,
        assignment_id=assignment_id,
        permission_key=permission_key,
        scope_type=scope_type,
        scope_key=scope_key,
        before=before,
        after=after,
        reason=reason,
        risk_level=risk_level,
        high_risk=high_risk,
        result=result,
        audit=audit,
        error_code=error_code,
        confirmation_provided=confirmation_provided,
    )


def _log_permission_failure_and_raise(
    db: Session,
    *,
    actor: User,
    action: str,
    target_user_id: int,
    permission_key: str | None,
    scope_type: str | None,
    scope_key: str | None,
    reason: str | None,
    risk_level: str | None,
    high_risk: bool,
    audit: AuditContext,
    error_code: str,
    exc: PermissionServiceError,
    assignment_id: UUID | None = None,
    before: dict[str, object] | None = None,
    confirmation_provided: bool = False,
) -> None:
    _write_permission_operation_log(
        db,
        actor=actor,
        action=action,
        target_user_id=target_user_id,
        assignment_id=assignment_id,
        permission_key=permission_key,
        scope_type=scope_type,
        scope_key=scope_key,
        before=before,
        after=None,
        reason=reason,
        risk_level=risk_level,
        high_risk=high_risk,
        result="failure",
        audit=audit,
        error_code=error_code,
        confirmation_provided=confirmation_provided,
    )
    db.commit()
    raise exc


def _validate_seed_permissions(
    seed_permissions: list[PermissionDefinition] | tuple[PermissionDefinition, ...],
) -> list[PermissionDefinition]:
    seen: set[str] = set()
    validated: list[PermissionDefinition] = []
    for permission in seed_permissions:
        item = validate_permission_definition(permission)
        if item["permission_key"] in seen:
            raise ValueError("Duplicate permission key in registry seed.")
        seen.add(item["permission_key"])
        validated.append(item)
    return validated


def list_permissions(db: Session) -> list[PermissionRegistry]:
    return list_permission_records(db)


def get_permission(
    db: Session,
    permission_key: str,
) -> PermissionRegistry | None:
    return get_permission_record(db, validate_permission_key(permission_key))


def list_enabled_permissions(db: Session) -> list[PermissionRegistry]:
    return list_enabled_permission_records(db)


def _enabled_permission_keys(db: Session) -> list[str]:
    return sorted(
        {
            permission.permission_key
            for permission in list_enabled_permission_records(db)
        }
    )


def upsert_permission_registry(
    db: Session,
    seed_permissions: list[PermissionDefinition] | tuple[PermissionDefinition, ...]
    = BASE_PERMISSION_REGISTRY_SEED,
) -> list[PermissionRegistry]:
    validated_permissions = _validate_seed_permissions(seed_permissions)
    permissions = upsert_permission_registry_records(
        db,
        validated_permissions,
    )
    retired_permissions = disable_retired_permission_registry_entries(
        db,
        active_permission_keys={
            permission["permission_key"] for permission in validated_permissions
        },
    )
    db.commit()
    clear_permission_ttl_cache()
    for permission in [*permissions, *retired_permissions]:
        db.refresh(permission)
    return permissions


def list_user_assignments(
    db: Session,
    user_id: int,
) -> list[UserPermissionAssignment]:
    return list_user_assignment_records(db, user_id)


def list_user_permission_assignments(
    db: Session,
    *,
    user_id: int,
    actor: User,
) -> PermissionAssignmentListResult:
    target_user = _require_user(db, user_id)
    ensure_actor_can_manage_target_permissions(actor, target_user)
    if is_owner_role(target_user.role):
        return PermissionAssignmentListResult(
            user_id=target_user.id,
            username=target_user.username,
            role=target_user.role,
            is_owner_full_access=False,
            owner_full_access_note=(
                "Owner is a platform role evaluated by UnifiedPermissionEngine "
                "and is not managed through permission assignments."
            ),
            assignments=[],
        )

    now = _utc_now()
    assignments = [
        _build_assignment_view(db, assignment, now=now)
        for assignment in list_user_assignment_records(db, user_id)
    ]
    return PermissionAssignmentListResult(
        user_id=target_user.id,
        username=target_user.username,
        role=target_user.role,
        is_owner_full_access=False,
        owner_full_access_note=None,
        assignments=assignments,
    )


def grant_user_permission(
    db: Session,
    *,
    user_id: int,
    permission_key: str,
    scope_type: str = SCOPE_GLOBAL,
    scope_key: str = "*",
    actor: User,
    audit: AuditContext,
    reason: str | None = None,
    expires_at: datetime | None = None,
    confirm_high_risk: bool = False,
    confirmation_text: str | None = None,
) -> PermissionAssignmentActionResult:
    action = PERMISSION_ASSIGNMENT_GRANT_ACTION
    normalized_key: str | None = None
    normalized_scope_type: str | None = None
    normalized_scope_key: str | None = None

    try:
        if permission_key.strip() == "*":
            _log_permission_failure_and_raise(
                db,
                actor=actor,
                action=action,
                target_user_id=user_id,
                permission_key=permission_key,
                scope_type=scope_type,
                scope_key=scope_key,
                reason=reason,
                risk_level=None,
                high_risk=True,
                audit=audit,
                error_code="wildcard_permission_not_allowed",
                exc=PermissionAssignmentWildcardError(
                    "Wildcard permission assignments are not allowed."
                ),
                confirmation_provided=confirm_high_risk,
            )
        normalized_key = validate_permission_key(permission_key)
        normalized_scope_type, normalized_scope_key = validate_scope(
            scope_type,
            scope_key,
        )
    except PermissionServiceError:
        raise
    except ValueError as exc:
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=permission_key,
            scope_type=scope_type,
            scope_key=scope_key,
            reason=reason,
            risk_level=None,
            high_risk=False,
            audit=audit,
            error_code="invalid_permission_assignment_request",
            exc=PermissionServiceError(str(exc)),
            confirmation_provided=confirm_high_risk,
        )

    target_user = db.get(User, user_id)
    if target_user is None:
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=normalized_key,
            scope_type=normalized_scope_type,
            scope_key=normalized_scope_key,
            reason=reason,
            risk_level=None,
            high_risk=False,
            audit=audit,
            error_code="target_user_not_found",
            exc=PermissionUserNotFoundError("User not found."),
            confirmation_provided=confirm_high_risk,
        )
    try:
        ensure_actor_can_manage_target_permissions(actor, target_user)
    except PermissionAssignmentScopeForbiddenError as exc:
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=normalized_key,
            scope_type=normalized_scope_type,
            scope_key=normalized_scope_key,
            reason=reason,
            risk_level=None,
            high_risk=False,
            audit=audit,
            error_code="assignment_scope_forbidden",
            exc=exc,
            confirmation_provided=confirm_high_risk,
        )
    if is_owner_role(target_user.role):
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=normalized_key,
            scope_type=normalized_scope_type,
            scope_key=normalized_scope_key,
            reason=reason,
            risk_level=None,
            high_risk=True,
            audit=audit,
            error_code="owner_assignment_not_allowed",
            exc=PermissionAssignmentOwnerTargetError(
                "Owner permissions are not managed through assignments."
            ),
            confirmation_provided=confirm_high_risk,
        )

    permission = get_permission_record(db, normalized_key)
    if permission is None or not permission.is_enabled:
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=normalized_key,
            scope_type=normalized_scope_type,
            scope_key=normalized_scope_key,
            reason=reason,
            risk_level=None,
            high_risk=False,
            audit=audit,
            error_code="permission_not_found",
            exc=PermissionNotFoundError("Permission not found."),
            confirmation_provided=confirm_high_risk,
        )

    high_risk = detect_high_risk_permission(permission)
    if high_risk and not _has_high_risk_confirmation(
        reason=reason,
        confirm_high_risk=confirm_high_risk,
        confirmation_text=confirmation_text,
    ):
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=normalized_key,
            scope_type=normalized_scope_type,
            scope_key=normalized_scope_key,
            reason=reason,
            risk_level=permission.risk_level,
            high_risk=True,
            audit=audit,
            error_code="high_risk_confirmation_required",
            exc=PermissionAssignmentHighRiskConfirmationError(
                "High-risk permission requires reason and confirmation."
            ),
            confirmation_provided=confirm_high_risk,
        )

    try:
        existing = prevent_duplicate_active_assignment(
            db,
            user_id=user_id,
            permission_key=normalized_key,
            scope_type=normalized_scope_type,
            scope_key=normalized_scope_key,
        )
    except PermissionAssignmentDuplicateError as exc:
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=normalized_key,
            scope_type=normalized_scope_type,
            scope_key=normalized_scope_key,
            reason=reason,
            risk_level=permission.risk_level,
            high_risk=high_risk,
            audit=audit,
            error_code="duplicate_active_assignment",
            exc=exc,
            assignment_id=None,
            confirmation_provided=confirm_high_risk,
        )

    before = _assignment_state(existing)
    if existing is not None:
        assignment = existing
        assignment.granted_by_user_id = actor.id
        assignment.reason = reason
        assignment.expires_at = expires_at
        assignment.is_enabled = True
        assignment = save_user_assignment(db, assignment)
    else:
        assignment = upsert_user_assignment(
            db,
            user_id=user_id,
            permission_key=normalized_key,
            scope_type=normalized_scope_type,
            scope_key=normalized_scope_key,
            granted_by_user_id=actor.id,
            reason=reason,
            expires_at=expires_at,
        )

    operation_id = _write_permission_operation_log(
        db,
        actor=actor,
        action=action,
        target_user_id=user_id,
        assignment_id=assignment.id,
        permission_key=normalized_key,
        scope_type=normalized_scope_type,
        scope_key=normalized_scope_key,
        before=before,
        after=_assignment_state(assignment),
        reason=reason,
        risk_level=permission.risk_level,
        high_risk=high_risk,
        result="success",
        audit=audit,
        confirmation_provided=confirm_high_risk,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise PermissionAssignmentDuplicateError(
            "Permission assignment already exists for that user and scope."
        ) from None
    clear_permission_ttl_cache()
    db.refresh(assignment)
    return PermissionAssignmentActionResult(
        assignment=_build_assignment_view(db, assignment, permission=permission),
        operation_id=operation_id,
    )


def _require_user_assignment_for_management(
    db: Session,
    *,
    user_id: int,
    assignment_id: UUID,
) -> tuple[User, UserPermissionAssignment]:
    target_user = _require_user(db, user_id)
    assignment = get_user_assignment_by_id(db, assignment_id)
    if assignment is None or assignment.user_id != user_id:
        raise PermissionAssignmentNotFoundError(
            "Permission assignment not found."
        )
    return target_user, assignment


def update_user_assignment(
    db: Session,
    *,
    user_id: int,
    assignment_id: UUID,
    payload: PermissionAssignmentUpdate,
    actor: User,
    audit: AuditContext,
) -> PermissionAssignmentActionResult:
    action = PERMISSION_ASSIGNMENT_UPDATE_ACTION
    try:
        target_user, assignment = _require_user_assignment_for_management(
            db,
            user_id=user_id,
            assignment_id=assignment_id,
        )
    except PermissionServiceError as exc:
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=None,
            scope_type=None,
            scope_key=None,
            reason=payload.reason,
            risk_level=None,
            high_risk=False,
            audit=audit,
            error_code=(
                "assignment_not_found"
                if isinstance(exc, PermissionAssignmentNotFoundError)
                else "target_user_not_found"
            ),
            exc=exc,
            assignment_id=assignment_id,
            confirmation_provided=payload.confirm_high_risk,
        )

    try:
        ensure_actor_can_manage_target_permissions(actor, target_user)
    except PermissionAssignmentScopeForbiddenError as exc:
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=assignment.permission_key,
            scope_type=None,
            scope_key=None,
            reason=payload.reason,
            risk_level=None,
            high_risk=False,
            audit=audit,
            error_code="assignment_scope_forbidden",
            exc=exc,
            assignment_id=assignment_id,
            confirmation_provided=payload.confirm_high_risk,
        )

    permission = get_permission_record(db, assignment.permission_key)
    high_risk = (
        detect_high_risk_permission(permission)
        if permission is not None
        else False
    )
    before = _assignment_state(assignment)

    if is_owner_role(target_user.role):
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=assignment.permission_key,
            scope_type=assignment.scope_type,
            scope_key=assignment.scope_key,
            reason=payload.reason,
            risk_level=permission.risk_level if permission else None,
            high_risk=True,
            audit=audit,
            error_code="owner_assignment_not_allowed",
            exc=PermissionAssignmentOwnerTargetError(
                "Owner permissions are not managed through assignments."
            ),
            assignment_id=assignment.id,
            before=before,
            confirmation_provided=payload.confirm_high_risk,
        )

    if payload.permission_key is not None:
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=assignment.permission_key,
            scope_type=assignment.scope_type,
            scope_key=assignment.scope_key,
            reason=payload.reason,
            risk_level=permission.risk_level if permission else None,
            high_risk=high_risk,
            audit=audit,
            error_code="permission_key_update_not_allowed",
            exc=PermissionAssignmentKeyUpdateNotAllowedError(
                "Permission key changes require revoke and grant."
            ),
            assignment_id=assignment.id,
            before=before,
            confirmation_provided=payload.confirm_high_risk,
        )

    fields_set = payload.model_fields_set
    requested_scope_key: str | None = None
    if "scope_id" in fields_set:
        requested_scope_key = payload.scope_id
    elif "scope_key" in fields_set:
        requested_scope_key = payload.scope_key

    new_scope_type = (
        payload.scope_type
        if "scope_type" in fields_set and payload.scope_type is not None
        else assignment.scope_type
    )
    new_scope_key = (
        requested_scope_key
        if requested_scope_key is not None
        else assignment.scope_key
    )
    try:
        new_scope_type, new_scope_key = validate_scope(
            new_scope_type,
            new_scope_key,
        )
    except ValueError as exc:
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=assignment.permission_key,
            scope_type=assignment.scope_type,
            scope_key=assignment.scope_key,
            reason=payload.reason,
            risk_level=permission.risk_level if permission else None,
            high_risk=high_risk,
            audit=audit,
            error_code="invalid_scope",
            exc=PermissionServiceError(str(exc)),
            assignment_id=assignment.id,
            before=before,
            confirmation_provided=payload.confirm_high_risk,
        )

    new_enabled = (
        payload.enabled
        if (
            ("enabled" in fields_set or "is_enabled" in fields_set)
            and payload.enabled is not None
        )
        else assignment.is_enabled
    )
    new_reason = payload.reason if "reason" in fields_set else assignment.reason
    new_expires_at = (
        payload.expires_at
        if "expires_at" in fields_set
        else assignment.expires_at
    )

    now = _utc_now()
    before_effective = _assignment_is_effective(
        assignment,
        permission,
        now=now,
    )
    after_effective = _assignment_values_are_effective(
        permission=permission,
        enabled=new_enabled,
        expires_at=new_expires_at,
        now=now,
    )
    scope_changed = _is_scope_expanded_or_changed(
        before_scope_type=assignment.scope_type,
        before_scope_key=assignment.scope_key,
        after_scope_type=new_scope_type,
        after_scope_key=new_scope_key,
    )
    requires_confirmation = high_risk and (
        (after_effective and not before_effective) or scope_changed
    )
    high_risk_sensitive_update = high_risk and (
        scope_changed
        or before_effective != after_effective
        or "expires_at" in fields_set
    )
    if high_risk_sensitive_update and not _has_reason(new_reason):
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=assignment.permission_key,
            scope_type=assignment.scope_type,
            scope_key=assignment.scope_key,
            reason=new_reason,
            risk_level=permission.risk_level if permission else None,
            high_risk=high_risk,
            audit=audit,
            error_code="high_risk_reason_required",
            exc=PermissionAssignmentHighRiskReasonError(
                "High-risk permission update requires a reason."
            ),
            assignment_id=assignment.id,
            before=before,
            confirmation_provided=payload.confirm_high_risk,
        )
    if requires_confirmation and not _has_high_risk_confirmation(
        reason=new_reason,
        confirm_high_risk=payload.confirm_high_risk,
        confirmation_text=payload.confirmation_text,
    ):
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=assignment.permission_key,
            scope_type=assignment.scope_type,
            scope_key=assignment.scope_key,
            reason=new_reason,
            risk_level=permission.risk_level if permission else None,
            high_risk=high_risk,
            audit=audit,
            error_code="high_risk_confirmation_required",
            exc=PermissionAssignmentHighRiskConfirmationError(
                "High-risk permission update requires confirmation."
            ),
            assignment_id=assignment.id,
            before=before,
            confirmation_provided=payload.confirm_high_risk,
        )

    if scope_changed:
        try:
            prevent_duplicate_active_assignment(
                db,
                user_id=user_id,
                permission_key=assignment.permission_key,
                scope_type=new_scope_type,
                scope_key=new_scope_key,
                exclude_assignment_id=assignment.id,
            )
        except PermissionAssignmentDuplicateError as exc:
            _log_permission_failure_and_raise(
                db,
                actor=actor,
                action=action,
                target_user_id=user_id,
                permission_key=assignment.permission_key,
                scope_type=new_scope_type,
                scope_key=new_scope_key,
                reason=new_reason,
                risk_level=permission.risk_level if permission else None,
                high_risk=high_risk,
                audit=audit,
                error_code="duplicate_active_assignment",
                exc=exc,
                assignment_id=assignment.id,
                before=before,
                confirmation_provided=payload.confirm_high_risk,
            )

    assignment.scope_type = new_scope_type
    assignment.scope_key = new_scope_key
    assignment.is_enabled = new_enabled
    assignment.reason = new_reason
    assignment.expires_at = new_expires_at
    assignment = save_user_assignment(db, assignment)
    operation_id = _write_permission_operation_log(
        db,
        actor=actor,
        action=action,
        target_user_id=user_id,
        assignment_id=assignment.id,
        permission_key=assignment.permission_key,
        scope_type=assignment.scope_type,
        scope_key=assignment.scope_key,
        before=before,
        after=_assignment_state(assignment),
        reason=new_reason,
        risk_level=permission.risk_level if permission else None,
        high_risk=high_risk,
        result="success",
        audit=audit,
        confirmation_provided=payload.confirm_high_risk,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise PermissionAssignmentDuplicateError(
            "Permission assignment already exists for that user and scope."
        ) from None
    clear_permission_ttl_cache()
    db.refresh(assignment)
    return PermissionAssignmentActionResult(
        assignment=_build_assignment_view(db, assignment, permission=permission),
        operation_id=operation_id,
    )


def revoke_user_assignment(
    db: Session,
    *,
    user_id: int,
    assignment_id: UUID,
    actor: User,
    audit: AuditContext,
    reason: str | None = None,
) -> PermissionAssignmentActionResult:
    action = PERMISSION_ASSIGNMENT_REVOKE_ACTION
    try:
        target_user, assignment = _require_user_assignment_for_management(
            db,
            user_id=user_id,
            assignment_id=assignment_id,
        )
    except PermissionServiceError as exc:
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=None,
            scope_type=None,
            scope_key=None,
            reason=reason,
            risk_level=None,
            high_risk=False,
            audit=audit,
            error_code=(
                "assignment_not_found"
                if isinstance(exc, PermissionAssignmentNotFoundError)
                else "target_user_not_found"
            ),
            exc=exc,
            assignment_id=assignment_id,
        )

    try:
        ensure_actor_can_manage_target_permissions(actor, target_user)
    except PermissionAssignmentScopeForbiddenError as exc:
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=assignment.permission_key,
            scope_type=None,
            scope_key=None,
            reason=reason,
            risk_level=None,
            high_risk=False,
            audit=audit,
            error_code="assignment_scope_forbidden",
            exc=exc,
            assignment_id=assignment_id,
        )

    permission = get_permission_record(db, assignment.permission_key)
    high_risk = (
        detect_high_risk_permission(permission)
        if permission is not None
        else False
    )
    before = _assignment_state(assignment)

    if is_owner_role(target_user.role):
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=assignment.permission_key,
            scope_type=assignment.scope_type,
            scope_key=assignment.scope_key,
            reason=reason,
            risk_level=permission.risk_level if permission else None,
            high_risk=True,
            audit=audit,
            error_code="owner_assignment_not_allowed",
            exc=PermissionAssignmentOwnerTargetError(
                "Owner permissions are not managed through assignments."
            ),
            assignment_id=assignment.id,
            before=before,
        )
    if high_risk and not _has_reason(reason):
        _log_permission_failure_and_raise(
            db,
            actor=actor,
            action=action,
            target_user_id=user_id,
            permission_key=assignment.permission_key,
            scope_type=assignment.scope_type,
            scope_key=assignment.scope_key,
            reason=reason,
            risk_level=permission.risk_level if permission else None,
            high_risk=high_risk,
            audit=audit,
            error_code="high_risk_reason_required",
            exc=PermissionAssignmentHighRiskReasonError(
                "High-risk permission revoke requires a reason."
            ),
            assignment_id=assignment.id,
            before=before,
        )

    assignment.is_enabled = False
    if reason is not None:
        assignment.reason = reason
    assignment = save_user_assignment(db, assignment)
    operation_id = _write_permission_operation_log(
        db,
        actor=actor,
        action=action,
        target_user_id=user_id,
        assignment_id=assignment.id,
        permission_key=assignment.permission_key,
        scope_type=assignment.scope_type,
        scope_key=assignment.scope_key,
        before=before,
        after=_assignment_state(assignment),
        reason=reason,
        risk_level=permission.risk_level if permission else None,
        high_risk=high_risk,
        result="success",
        audit=audit,
    )
    db.commit()
    clear_permission_ttl_cache()
    db.refresh(assignment)
    return PermissionAssignmentActionResult(
        assignment=_build_assignment_view(db, assignment, permission=permission),
        operation_id=operation_id,
    )


def grant_permission(
    db: Session,
    *,
    user_id: int,
    permission_key: str,
    scope_type: str = SCOPE_GLOBAL,
    scope_key: str = "*",
    granted_by_user_id: int | None = None,
    reason: str | None = None,
    expires_at: datetime | None = None,
) -> UserPermissionAssignment:
    normalized_key = validate_permission_key(permission_key)
    normalized_scope_type, normalized_scope_key = validate_scope(
        scope_type,
        scope_key,
    )
    _require_user(db, user_id)
    if granted_by_user_id is not None:
        _require_user(db, granted_by_user_id)
    _require_enabled_permission(db, normalized_key)

    assignment = upsert_user_assignment(
        db,
        user_id=user_id,
        permission_key=normalized_key,
        scope_type=normalized_scope_type,
        scope_key=normalized_scope_key,
        granted_by_user_id=granted_by_user_id,
        reason=reason,
        expires_at=expires_at,
    )
    db.commit()
    clear_permission_ttl_cache()
    db.refresh(assignment)
    return assignment


def disable_assignment(
    db: Session,
    assignment_id: UUID,
) -> UserPermissionAssignment:
    assignment = get_user_assignment_by_id(db, assignment_id)
    if assignment is None:
        raise PermissionAssignmentNotFoundError("Permission assignment not found.")
    assignment = disable_assignment_record(db, assignment)
    db.commit()
    clear_permission_ttl_cache()
    db.refresh(assignment)
    return assignment


def revoke_permission(
    db: Session,
    *,
    user_id: int,
    permission_key: str,
    scope_type: str = SCOPE_GLOBAL,
    scope_key: str = "*",
) -> UserPermissionAssignment:
    normalized_key = validate_permission_key(permission_key)
    normalized_scope_type, normalized_scope_key = validate_scope(
        scope_type,
        scope_key,
    )
    assignment = get_user_assignment(
        db,
        user_id=user_id,
        permission_key=normalized_key,
        scope_type=normalized_scope_type,
        scope_key=normalized_scope_key,
    )
    if assignment is None:
        raise PermissionAssignmentNotFoundError("Permission assignment not found.")
    assignment = disable_assignment_record(db, assignment)
    db.commit()
    clear_permission_ttl_cache()
    db.refresh(assignment)
    return assignment


def user_has_permission(
    db: Session,
    user: User,
    permission_key: str,
    scope_type: str = SCOPE_GLOBAL,
    scope_key: str = "*",
) -> bool:
    module_id, _, action = permission_key.partition(".")
    decision = PermissionDecisionEngine(db).decide(
        UnifiedPermissionRequest(
            user_id=user.id,
            org_id=scope_key if scope_type == SCOPE_ORGANIZATION else None,
            module_id=module_id or "permissions",
            action=action or "read",
            role=user.role,
            scope_type=scope_type,
            scope_key=scope_key,
            permission_key=permission_key,
            source="c05_user_has_permission_wrapper",
        )
    )
    return decision.allowed


def resolve_effective_permissions(
    db: Session,
    user: User,
) -> EffectivePermissions:
    role = normalize_role(user.role)

    if is_owner_role(role):
        return EffectivePermissions(
            user_id=user.id,
            role=role,
            is_owner_full_access=True,
            permissions=["*"],
            scoped_permissions=[],
            is_platform_owner=True,
        )

    if is_super_admin_role(role):
        return EffectivePermissions(
            user_id=user.id,
            role=role,
            is_owner_full_access=False,
            permissions=_enabled_permission_keys(db),
            scoped_permissions=[],
            is_platform_owner=False,
        )

    now = _utc_now()
    assignments = list_enabled_user_assignments(db, user.id, now=now)
    scoped_permissions = [
        EffectivePermissionScope(
            permission_key=assignment.permission_key,
            scope_type=assignment.scope_type,
            scope_key=assignment.scope_key,
            expires_at=assignment.expires_at,
        )
        for assignment in assignments
        if not _is_expired(assignment.expires_at, now=now)
    ]
    permission_keys = sorted(
        {permission.permission_key for permission in scoped_permissions}
    )
    return EffectivePermissions(
        user_id=user.id,
        role=role,
        is_owner_full_access=False,
        permissions=permission_keys,
        scoped_permissions=scoped_permissions,
        is_platform_owner=False,
    )


def resolve_current_user_permission_info(
    db: Session,
    user: User,
    *,
    request: object | None = None,
) -> CurrentUserPermissionInfo:
    role = normalize_role(user.role)
    if request is None or is_owner_role(role) or is_super_admin_role(role):
        effective = resolve_effective_permissions(db, user)
        return _current_user_permission_info_from_effective(effective)

    resolution_cache = PermissionResolutionCache(request=request)
    now = _utc_now()
    scope_rows = resolution_cache.list_user_permission_scopes(
        db,
        user_id=user.id,
        now=now,
    )
    scoped_permissions = [
        EffectivePermissionScope(
            permission_key=row.permission_key,
            scope_type=row.scope_type,
            scope_key=row.scope_key,
            expires_at=row.expires_at,
        )
        for row in scope_rows
    ]
    effective = EffectivePermissions(
        user_id=user.id,
        role=role,
        is_owner_full_access=False,
        permissions=sorted(
            {permission.permission_key for permission in scoped_permissions}
        ),
        scoped_permissions=scoped_permissions,
        is_platform_owner=False,
    )
    return _current_user_permission_info_from_effective(effective)


def _current_user_permission_info_from_effective(
    effective: EffectivePermissions,
) -> CurrentUserPermissionInfo:
    assignments = [
        EffectivePermissionAssignment(
            permission_key=permission.permission_key,
            scope_type=permission.scope_type,
            scope_key=permission.scope_key,
        )
        for permission in effective.scoped_permissions
    ]
    scope_permissions: dict[tuple[str, str], set[str]] = {}
    for permission in effective.scoped_permissions:
        scope_permissions.setdefault(
            (permission.scope_type, permission.scope_key),
            set(),
        ).add(permission.permission_key)

    scope_summary = [
        EffectivePermissionScopeSummary(
            scope_type=scope_type,
            scope_key=scope_key,
            permission_keys=sorted(permission_keys),
        )
        for (scope_type, scope_key), permission_keys in sorted(
            scope_permissions.items()
        )
    ]
    return CurrentUserPermissionInfo(
        is_owner_full_access=effective.is_owner_full_access,
        permission_keys=effective.permissions,
        assignments=assignments,
        scope_summary=scope_summary,
        is_platform_owner=effective.is_platform_owner,
    )


def resolve_current_user_module_permission_info(
    db: Session,
    user: User,
    *,
    request: object | None = None,
) -> CurrentUserPermissionInfo:
    role = normalize_role(user.role)
    request_cache = get_permission_request_cache(request)
    cache_key = (
        MODULES_ME_PERMISSION_INFO_CACHE_NAMESPACE,
        (user.id, role),
    )
    if request_cache is not None and cache_key in request_cache.materials:
        request_cache.request_material_hits += 1
        return request_cache.materials[cache_key]

    if is_owner_role(role) or is_super_admin_role(role):
        effective = resolve_effective_permissions(db, user)
    else:
        resolution_cache = PermissionResolutionCache(request=request)
        now = _utc_now()
        scope_rows = resolution_cache.list_user_permission_scopes(
            db,
            user_id=user.id,
            now=now,
        )
        scoped_permissions = [
            EffectivePermissionScope(
                permission_key=row.permission_key,
                scope_type=row.scope_type,
                scope_key=row.scope_key,
                expires_at=row.expires_at,
            )
            for row in scope_rows
        ]
        effective = EffectivePermissions(
            user_id=user.id,
            role=role,
            is_owner_full_access=False,
            permissions=sorted(
                {permission.permission_key for permission in scoped_permissions}
            ),
            scoped_permissions=scoped_permissions,
            is_platform_owner=False,
        )

    info = _current_user_permission_info_from_effective(effective)
    if request_cache is not None:
        request_cache.materials[cache_key] = info
    return info


def list_role_default_permissions(
    db: Session,
    role: str | None = None,
) -> list[RoleDefaultPermission]:
    normalized_role = normalize_role(role) if role is not None else None
    return list_role_default_permission_records(db, normalized_role)


def upsert_role_default_permission(
    db: Session,
    *,
    role: str,
    permission_key: str,
    scope_type: str = SCOPE_GLOBAL,
    scope_key: str = "*",
    is_enabled: bool = True,
) -> RoleDefaultPermission:
    normalized_role = normalize_role(role)
    normalized_key = validate_permission_key(permission_key)
    normalized_scope_type, normalized_scope_key = validate_scope(
        scope_type,
        scope_key,
    )
    _require_enabled_permission(db, normalized_key)
    default_permission = upsert_role_default_permission_record(
        db,
        role=normalized_role,
        permission_key=normalized_key,
        scope_type=normalized_scope_type,
        scope_key=normalized_scope_key,
        is_enabled=is_enabled,
    )
    db.commit()
    clear_permission_ttl_cache()
    db.refresh(default_permission)
    return default_permission
