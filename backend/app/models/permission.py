from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from ..db.base import Base
from .base_mixins import TimestampMixin


class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
    )


class PermissionRegistry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "permission_registry"
    __table_args__ = (
        Index(
            "ix_permission_registry_enabled_category",
            "is_enabled",
            "category",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="valid_risk_level",
        ),
        CheckConstraint(
            "menu_policy IN ('show_locked', 'hide_when_denied')",
            name="valid_menu_policy",
        ),
    )

    permission_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )
    module_key: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="low",
    )
    menu_policy: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="hide_when_denied",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=true(),
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=true(),
    )


class UserPermissionAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_permission_assignments"
    __table_args__ = (
        Index(
            "ix_user_permission_assignments_user_enabled_expires",
            "user_id",
            "is_enabled",
            "expires_at",
        ),
        Index(
            "ix_user_permission_assignments_user_scope",
            "user_id",
            "scope_type",
            "scope_key",
        ),
        UniqueConstraint(
            "user_id",
            "permission_key",
            "scope_type",
            "scope_key",
            name="uq_user_permission_assignments_user_permission_scope",
        ),
        CheckConstraint(
            "scope_type IN ("
            "'global', 'company', 'factory', 'department', "
            "'organization', 'module'"
            ")",
            name="valid_scope_type",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )
    permission_key: Mapped[str] = mapped_column(
        ForeignKey("permission_registry.permission_key"),
        nullable=False,
    )
    scope_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="global",
    )
    scope_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default="*",
    )
    granted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=true(),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class RoleDefaultPermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "role_default_permissions"
    __table_args__ = (
        UniqueConstraint(
            "role",
            "permission_key",
            "scope_type",
            "scope_key",
            name="uq_role_default_permissions_role_permission_scope",
        ),
        CheckConstraint(
            "scope_type IN ("
            "'global', 'company', 'factory', 'department', "
            "'organization', 'module'"
            ")",
            name="valid_scope_type",
        ),
    )

    role: Mapped[str] = mapped_column(String(50), nullable=False)
    permission_key: Mapped[str] = mapped_column(
        ForeignKey("permission_registry.permission_key"),
        nullable=False,
    )
    scope_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="global",
    )
    scope_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default="*",
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=true(),
    )
