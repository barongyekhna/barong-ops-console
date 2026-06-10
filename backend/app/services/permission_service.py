from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from ..core.permissions import (
    BASE_PERMISSION_REGISTRY_SEED,
    PermissionDefinition,
    SCOPE_GLOBAL,
    validate_permission_definition,
    validate_permission_key,
    validate_scope,
)
from ..core.roles import is_owner_role, normalize_role
from ..models.permission import (
    PermissionRegistry,
    RoleDefaultPermission,
    UserPermissionAssignment,
)
from ..models.user import User
from ..repositories.permissions import (
    disable_assignment as disable_assignment_record,
    get_permission as get_permission_record,
    get_user_assignment,
    get_user_assignment_by_id,
    list_enabled_permissions as list_enabled_permission_records,
    list_enabled_user_assignments,
    list_permissions as list_permission_records,
    list_role_default_permissions as list_role_default_permission_records,
    list_user_assignments as list_user_assignment_records,
    upsert_permission_registry as upsert_permission_registry_records,
    upsert_role_default_permission as upsert_role_default_permission_record,
    upsert_user_assignment,
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


def upsert_permission_registry(
    db: Session,
    seed_permissions: list[PermissionDefinition] | tuple[PermissionDefinition, ...]
    = BASE_PERMISSION_REGISTRY_SEED,
) -> list[PermissionRegistry]:
    permissions = upsert_permission_registry_records(
        db,
        _validate_seed_permissions(seed_permissions),
    )
    db.commit()
    for permission in permissions:
        db.refresh(permission)
    return permissions


def list_user_assignments(
    db: Session,
    user_id: int,
) -> list[UserPermissionAssignment]:
    return list_user_assignment_records(db, user_id)


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
    db.refresh(assignment)
    return assignment


def user_has_permission(
    db: Session,
    user: User,
    permission_key: str,
    scope_type: str = SCOPE_GLOBAL,
    scope_key: str = "*",
) -> bool:
    normalized_key = validate_permission_key(permission_key)
    normalized_scope_type, normalized_scope_key = validate_scope(
        scope_type,
        scope_key,
    )
    if is_owner_role(user.role):
        return True

    permission = get_permission(db, normalized_key)
    if permission is None or not permission.is_enabled:
        return False

    now = _utc_now()
    assignments = list_enabled_user_assignments(db, user.id, now=now)
    for assignment in assignments:
        if assignment.permission_key != normalized_key:
            continue
        if _is_expired(assignment.expires_at, now=now):
            continue
        if _assignment_matches_scope(
            assignment,
            scope_type=normalized_scope_type,
            scope_key=normalized_scope_key,
        ):
            return True
    return False


def resolve_effective_permissions(
    db: Session,
    user: User,
) -> EffectivePermissions:
    role = normalize_role(user.role)
    enabled_permissions = list_enabled_permissions(db)

    if is_owner_role(role):
        permission_keys = sorted(
            permission.permission_key for permission in enabled_permissions
        )
        return EffectivePermissions(
            user_id=user.id,
            role=role,
            is_owner_full_access=True,
            permissions=permission_keys,
            scoped_permissions=[
                EffectivePermissionScope(
                    permission_key=permission.permission_key,
                    scope_type=SCOPE_GLOBAL,
                    scope_key="*",
                    expires_at=None,
                )
                for permission in enabled_permissions
            ],
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
    )


def resolve_current_user_permission_info(
    db: Session,
    user: User,
) -> CurrentUserPermissionInfo:
    effective = resolve_effective_permissions(db, user)
    if effective.is_owner_full_access:
        return CurrentUserPermissionInfo(
            is_owner_full_access=True,
            permission_keys=["*"],
            assignments=[],
            scope_summary=[],
        )

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
        is_owner_full_access=False,
        permission_keys=effective.permissions,
        assignments=assignments,
        scope_summary=scope_summary,
    )


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
    db.refresh(default_permission)
    return default_permission
