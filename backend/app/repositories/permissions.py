from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.permissions import PermissionDefinition, RETIRED_PERMISSION_PREFIXES
from ..models.permission import (
    PermissionRegistry,
    RoleDefaultPermission,
    UserPermissionAssignment,
)


def list_permissions(db: Session) -> list[PermissionRegistry]:
    return list(
        db.scalars(
            select(PermissionRegistry).order_by(
                PermissionRegistry.module_key,
                PermissionRegistry.permission_key,
            )
        )
    )


def list_enabled_permissions(db: Session) -> list[PermissionRegistry]:
    return list(
        db.scalars(
            select(PermissionRegistry)
            .where(PermissionRegistry.is_enabled.is_(True))
            .order_by(
                PermissionRegistry.module_key,
                PermissionRegistry.permission_key,
            )
        )
    )


def list_enabled_permission_keys_by_categories(
    db: Session,
    categories: frozenset[str] | tuple[str, ...],
) -> list[str]:
    return list(
        db.scalars(
            select(PermissionRegistry.permission_key)
            .where(
                PermissionRegistry.is_enabled.is_(True),
                PermissionRegistry.category.in_(tuple(sorted(categories))),
            )
            .order_by(PermissionRegistry.permission_key)
        )
    )


def get_permission(
    db: Session,
    permission_key: str,
) -> PermissionRegistry | None:
    return db.scalar(
        select(PermissionRegistry).where(
            PermissionRegistry.permission_key == permission_key
        )
    )


def upsert_permission_registry(
    db: Session,
    seed_permissions: list[PermissionDefinition],
) -> list[PermissionRegistry]:
    permissions: list[PermissionRegistry] = []
    for seed in seed_permissions:
        permission = get_permission(db, seed["permission_key"])
        if permission is None:
            permission = PermissionRegistry(
                permission_key=seed["permission_key"],
            )
        permission.module_key = seed["module_key"]
        permission.category = seed["category"]
        permission.action = seed["action"]
        permission.label = seed["label"]
        permission.description = seed["description"]
        permission.risk_level = seed["risk_level"]
        permission.menu_policy = seed["menu_policy"]
        permission.is_system = True
        permission.is_enabled = True
        db.add(permission)
        permissions.append(permission)

    db.flush()
    return permissions


def disable_retired_permission_registry_entries(
    db: Session,
    *,
    active_permission_keys: set[str],
    retired_prefixes: tuple[str, ...] = RETIRED_PERMISSION_PREFIXES,
) -> list[PermissionRegistry]:
    retired_permissions: list[PermissionRegistry] = []
    for permission in list_permissions(db):
        if permission.permission_key in active_permission_keys:
            continue
        if not permission.is_enabled:
            continue
        if not any(
            permission.permission_key.startswith(prefix)
            for prefix in retired_prefixes
        ):
            continue
        permission.is_enabled = False
        db.add(permission)
        retired_permissions.append(permission)

    db.flush()
    return retired_permissions


def list_user_assignments(
    db: Session,
    user_id: int,
) -> list[UserPermissionAssignment]:
    return list(
        db.scalars(
            select(UserPermissionAssignment)
            .where(UserPermissionAssignment.user_id == user_id)
            .order_by(
                UserPermissionAssignment.permission_key,
                UserPermissionAssignment.scope_type,
                UserPermissionAssignment.scope_key,
            )
        )
    )


def list_enabled_user_assignments(
    db: Session,
    user_id: int,
    *,
    now: datetime,
) -> list[UserPermissionAssignment]:
    return list(
        db.scalars(
            select(UserPermissionAssignment)
            .join(
                PermissionRegistry,
                PermissionRegistry.permission_key
                == UserPermissionAssignment.permission_key,
            )
            .where(
                UserPermissionAssignment.user_id == user_id,
                UserPermissionAssignment.is_enabled.is_(True),
                PermissionRegistry.is_enabled.is_(True),
                (
                    UserPermissionAssignment.expires_at.is_(None)
                    | (UserPermissionAssignment.expires_at > now)
                ),
            )
            .order_by(
                UserPermissionAssignment.permission_key,
                UserPermissionAssignment.scope_type,
                UserPermissionAssignment.scope_key,
            )
        )
    )


def list_enabled_user_permission_scope_rows(
    db: Session,
    user_id: int,
    *,
    now: datetime,
) -> list[tuple[str, str, str, datetime | None]]:
    rows = db.execute(
        select(
            UserPermissionAssignment.permission_key,
            UserPermissionAssignment.scope_type,
            UserPermissionAssignment.scope_key,
            UserPermissionAssignment.expires_at,
        )
        .join(
            PermissionRegistry,
            PermissionRegistry.permission_key
            == UserPermissionAssignment.permission_key,
        )
        .where(
            UserPermissionAssignment.user_id == user_id,
            UserPermissionAssignment.is_enabled.is_(True),
            PermissionRegistry.is_enabled.is_(True),
            (
                UserPermissionAssignment.expires_at.is_(None)
                | (UserPermissionAssignment.expires_at > now)
            ),
        )
        .order_by(
            UserPermissionAssignment.permission_key,
            UserPermissionAssignment.scope_type,
            UserPermissionAssignment.scope_key,
        )
    ).all()
    return [
        (
            row.permission_key,
            row.scope_type,
            row.scope_key,
            row.expires_at,
        )
        for row in rows
    ]


def get_user_assignment(
    db: Session,
    *,
    user_id: int,
    permission_key: str,
    scope_type: str,
    scope_key: str,
) -> UserPermissionAssignment | None:
    return db.scalar(
        select(UserPermissionAssignment).where(
            UserPermissionAssignment.user_id == user_id,
            UserPermissionAssignment.permission_key == permission_key,
            UserPermissionAssignment.scope_type == scope_type,
            UserPermissionAssignment.scope_key == scope_key,
        )
    )


def get_user_assignment_by_id(
    db: Session,
    assignment_id: UUID,
) -> UserPermissionAssignment | None:
    return db.get(UserPermissionAssignment, assignment_id)


def upsert_user_assignment(
    db: Session,
    *,
    user_id: int,
    permission_key: str,
    scope_type: str,
    scope_key: str,
    granted_by_user_id: int | None,
    reason: str | None,
    expires_at: datetime | None,
) -> UserPermissionAssignment:
    assignment = get_user_assignment(
        db,
        user_id=user_id,
        permission_key=permission_key,
        scope_type=scope_type,
        scope_key=scope_key,
    )
    if assignment is None:
        assignment = UserPermissionAssignment(
            user_id=user_id,
            permission_key=permission_key,
            scope_type=scope_type,
            scope_key=scope_key,
        )

    assignment.granted_by_user_id = granted_by_user_id
    assignment.reason = reason
    assignment.expires_at = expires_at
    assignment.is_enabled = True
    db.add(assignment)
    db.flush()
    return assignment


def disable_assignment(
    db: Session,
    assignment: UserPermissionAssignment,
) -> UserPermissionAssignment:
    assignment.is_enabled = False
    db.add(assignment)
    db.flush()
    return assignment


def save_user_assignment(
    db: Session,
    assignment: UserPermissionAssignment,
) -> UserPermissionAssignment:
    db.add(assignment)
    db.flush()
    return assignment


def list_role_default_permissions(
    db: Session,
    role: str | None = None,
) -> list[RoleDefaultPermission]:
    statement = select(RoleDefaultPermission).order_by(
        RoleDefaultPermission.role,
        RoleDefaultPermission.permission_key,
        RoleDefaultPermission.scope_type,
        RoleDefaultPermission.scope_key,
    )
    if role is not None:
        statement = statement.where(RoleDefaultPermission.role == role)

    return list(db.scalars(statement))


def upsert_role_default_permission(
    db: Session,
    *,
    role: str,
    permission_key: str,
    scope_type: str,
    scope_key: str,
    is_enabled: bool = True,
) -> RoleDefaultPermission:
    default_permission = db.scalar(
        select(RoleDefaultPermission).where(
            RoleDefaultPermission.role == role,
            RoleDefaultPermission.permission_key == permission_key,
            RoleDefaultPermission.scope_type == scope_type,
            RoleDefaultPermission.scope_key == scope_key,
        )
    )
    if default_permission is None:
        default_permission = RoleDefaultPermission(
            role=role,
            permission_key=permission_key,
            scope_type=scope_type,
            scope_key=scope_key,
        )

    default_permission.is_enabled = is_enabled
    db.add(default_permission)
    db.flush()
    return default_permission
