from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.app.core.permissions import BASE_PERMISSION_REGISTRY_SEED
from backend.app.db.base import Base
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
        expected_permissions = {
            "users.manage",
            "permissions.manage",
            "modules.read",
            "w.site_ops.read",
            "w.site_ops.manage",
        }

        assert permission_count == len(BASE_PERMISSION_REGISTRY_SEED)
        assert len(permission_keys) == len(set(permission_keys))
        assert expected_permissions.issubset(set(permission_keys))

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


def test_registry_sync_retires_legacy_c19_permissions_and_assignments_are_inert(
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            PermissionRegistry.__table__,
            UserPermissionAssignment.__table__,
            RoleDefaultPermission.__table__,
        ],
    )
    permission_key = "c19.messages.send"
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(
            username="permission_legacy_c19",
            password_hash="test-only-hash",
            role="operator",
            is_active=True,
        )
        db.add(user)
        db.flush()
        legacy = PermissionRegistry(
            permission_key=permission_key,
            module_key="communication.im",
            category="core",
            action="send",
            label="Legacy C19 send",
            description="Retained only for assignment audit history.",
            risk_level="medium",
            menu_policy="show_locked",
            is_system=True,
            is_enabled=True,
        )
        db.add(legacy)
        db.flush()
        assignment = UserPermissionAssignment(
            user_id=user.id,
            permission_key=permission_key,
            scope_type="global",
            scope_key="*",
            is_enabled=True,
        )
        db.add(assignment)
        db.commit()

        upsert_permission_registry(db)
        db.refresh(legacy)
        db.refresh(assignment)

        assert legacy.is_enabled is False
        assert assignment.is_enabled is True
        assert not user_has_permission(db, user, permission_key)
        assert permission_key not in resolve_effective_permissions(
            db,
            user,
        ).permissions
    engine.dispose()


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


def test_super_admin_inherits_enabled_permissions_without_assignment(
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

        effective = resolve_effective_permissions(db, super_admin)

        assert user_has_permission(db, super_admin, "users.manage")
        assert user_has_permission(db, super_admin, "permissions.manage")
        assert user_has_permission(db, super_admin, "k.product_knowledge.update")
        assert user_has_permission(
            db,
            super_admin,
            "users.manage",
            scope_type="company",
            scope_key="independent_site",
        )
        assert user_has_permission(
            db,
            super_admin,
            "users.manage",
            scope_type="company",
            scope_key="factory_company",
        )
        assert user_has_permission(
            db,
            super_admin,
            "users.manage",
            scope_type="factory",
            scope_key="factory_a",
        )
        assert effective.is_owner_full_access is False
        assert effective.is_platform_owner is False
        assert "*" not in effective.permissions
        assert {"users.manage", "permissions.manage", "k.product_knowledge.update"}.issubset(
            set(effective.permissions)
        )


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


def test_role_default_permissions_do_not_change_super_admin_inheritance(
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
        assert user_has_permission(db, super_admin, "permissions.manage")
        assert "permissions.manage" in effective.permissions
        assert "*" not in effective.permissions


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
