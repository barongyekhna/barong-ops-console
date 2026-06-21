from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.app.core.permissions import BASE_PERMISSION_REGISTRY_SEED
from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.permission import (
    PermissionRegistry,
    RoleDefaultPermission,
    UserPermissionAssignment,
)
from backend.app.models.user import User
from backend.app.services.permission_service import (
    grant_permission,
    resolve_effective_permissions,
    revoke_permission,
    upsert_permission_registry,
    upsert_role_default_permission,
    user_has_permission,
)


def create_permission_test_user(
    *,
    username: str,
    role: str,
) -> int:
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password("example-only-permission-password"),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return user.id


def test_permission_registry_seed_upsert_is_idempotent(
    clean_auth_tables: None,
) -> None:
    with SessionLocal() as db:
        upsert_permission_registry(db)
        upsert_permission_registry(db)

        permission_count = db.scalar(
            select(func.count()).select_from(PermissionRegistry)
        )
        permission_keys = list(
            db.scalars(select(PermissionRegistry.permission_key))
        )
        core_permissions = {
            "users.manage",
            "permissions.manage",
            "modules.read",
        }

        assert permission_count == len(BASE_PERMISSION_REGISTRY_SEED)
        assert len(permission_keys) == len(set(permission_keys))
        assert core_permissions.issubset(set(permission_keys))

        db.add(
            PermissionRegistry(
                permission_key="users.manage",
                module_key="users",
                category="admin",
                action="manage",
                label="Duplicate users manage",
                description="Duplicate test row.",
                risk_level="high",
                menu_policy="hide_when_denied",
                is_system=True,
                is_enabled=True,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_owner_has_platform_admin_scope_without_assignments(
    clean_auth_tables: None,
) -> None:
    owner_id = create_permission_test_user(
        username="permission_owner",
        role="owner",
    )

    with SessionLocal() as db:
        upsert_permission_registry(db)
        owner = db.get(User, owner_id)
        assert owner is not None

        owner_assignments = list_user_assignments(db, owner_id)
        effective = resolve_effective_permissions(db, owner)

        assert owner_assignments == []
        assert user_has_permission(db, owner, "users.manage")
        assert user_has_permission(db, owner, "production.release")
        assert not user_has_permission(
            db,
            owner,
            "users.manage",
            scope_type="company",
            scope_key="independent_site",
        )
        assert not user_has_permission(
            db,
            owner,
            "production.release",
            scope_type="factory",
            scope_key="factory_a",
        )
        assert effective.is_owner_full_access is True
        assert effective.is_platform_owner is True
        assert effective.permissions == ["*"]
        assert "artifacts.read" not in effective.permissions


def test_super_admin_requires_assignment_and_scope_matches(
    clean_auth_tables: None,
) -> None:
    super_admin_id = create_permission_test_user(
        username="permission_super_admin",
        role="super_admin",
    )

    with SessionLocal() as db:
        upsert_permission_registry(db)
        super_admin = db.get(User, super_admin_id)
        assert super_admin is not None

        assert not user_has_permission(db, super_admin, "users.manage")

        assignment = grant_permission(
            db,
            user_id=super_admin_id,
            permission_key="users.manage",
            scope_type="company",
            scope_key="independent_site",
            reason="C05B scoped assignment test.",
        )
        effective = resolve_effective_permissions(db, super_admin)

        assert assignment.scope_type == "company"
        assert user_has_permission(
            db,
            super_admin,
            "users.manage",
            scope_type="company",
            scope_key="independent_site",
        )
        assert not user_has_permission(db, super_admin, "users.manage")
        assert not user_has_permission(
            db,
            super_admin,
            "users.manage",
            scope_type="company",
            scope_key="factory_company",
        )
        assert not user_has_permission(
            db,
            super_admin,
            "users.manage",
            scope_type="factory",
            scope_key="factory_a",
        )
        assert effective.is_owner_full_access is False
        assert effective.permissions == ["users.manage"]


def test_disabled_and_expired_assignments_do_not_apply(
    clean_auth_tables: None,
) -> None:
    user_id = create_permission_test_user(
        username="permission_operator",
        role="operator",
    )

    with SessionLocal() as db:
        upsert_permission_registry(db)
        user = db.get(User, user_id)
        assert user is not None

        assignment = grant_permission(
            db,
            user_id=user_id,
            permission_key="reviews.approve",
        )
        assert user_has_permission(db, user, "reviews.approve")

        revoked = revoke_permission(
            db,
            user_id=user_id,
            permission_key="reviews.approve",
        )
        assert revoked.id == assignment.id
        assert not user_has_permission(db, user, "reviews.approve")

        expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        grant_permission(
            db,
            user_id=user_id,
            permission_key="modules.read",
            expires_at=expired_at,
        )
        assert not user_has_permission(db, user, "modules.read")


def test_role_default_permissions_do_not_grant_effective_access(
    clean_auth_tables: None,
) -> None:
    super_admin_id = create_permission_test_user(
        username="permission_default_super_admin",
        role="super_admin",
    )

    with SessionLocal() as db:
        upsert_permission_registry(db)
        default_permission = upsert_role_default_permission(
            db,
            role="super_admin",
            permission_key="permissions.manage",
        )
        super_admin = db.get(User, super_admin_id)
        assert super_admin is not None

        effective = resolve_effective_permissions(db, super_admin)
        stored_defaults = list(
            db.scalars(select(RoleDefaultPermission).order_by(RoleDefaultPermission.id))
        )

        assert default_permission.is_enabled is True
        assert stored_defaults == [default_permission]
        assert not user_has_permission(db, super_admin, "permissions.manage")
        assert effective.permissions == []


def list_user_assignments(
    db,
    user_id: int,
) -> list[UserPermissionAssignment]:
    return list(
        db.scalars(
            select(UserPermissionAssignment)
            .where(UserPermissionAssignment.user_id == user_id)
            .order_by(UserPermissionAssignment.id)
        )
    )
