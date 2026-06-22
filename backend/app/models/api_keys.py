from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import PrimaryKeyMixin, TimestampMixin, json_type


class ApiKeyRecord(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_key_records"
    __table_args__ = (
        UniqueConstraint("key_id", name="uq_api_key_records_key_id"),
        Index("ix_api_key_records_org_id_status", "org_id", "status"),
        Index("ix_api_key_records_name", "name"),
    )

    key_id: Mapped[str] = mapped_column(String(40), nullable=False)
    org_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    encrypted_key_value: Mapped[str] = mapped_column(Text, nullable=False)
    key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    key_hash_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        json_type(),
        nullable=False,
        default=dict,
        server_default="{}",
    )


class ApiKeyModuleBindingRecord(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_key_module_bindings"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "module_id",
            "key_id",
            name="uq_api_key_module_bindings_org_module_key",
        ),
        Index("ix_api_key_module_bindings_org_module", "org_id", "module_id"),
        Index("ix_api_key_module_bindings_key_id", "key_id"),
    )

    binding_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    org_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    module_id: Mapped[str] = mapped_column(String(128), nullable=False)
    key_id: Mapped[str] = mapped_column(String(40), nullable=False)
    key_alias: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="default",
        server_default="default",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
