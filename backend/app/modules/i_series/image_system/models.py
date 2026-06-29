"""SQLAlchemy models for the independent I-series image media library."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ....db.base import Base
from ....models.base_mixins import json_type
from .constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_SCOPE_MODE,
    DEFAULT_WORKSPACE_KEY,
    MEDIA_BUCKET_EDITED,
    MEDIA_BUCKET_GENERATED,
    ORIGIN_I_DIRECT,
    ORIGIN_K_HANDOFF,
    SOURCE_EDIT,
    SOURCE_GENERATE,
    STATUS_GENERATED,
    STATUS_PROCESSING,
    STATUS_REMOVED,
    STATUS_STORED,
    STATUS_TEMP,
    TARGET_ORGANIZATION_NAME,
)


class IUUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class ITimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class IImageAsset(IUUIDPrimaryKeyMixin, ITimestampMixin, Base):
    __tablename__ = "i_image_system_assets"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('generate', 'edit')",
            name=conv("ck_i_image_assets_valid_source_type"),
        ),
        CheckConstraint(
            "status IN ('TEMP', 'PROCESSING', 'GENERATED', 'STORED', 'REMOVED')",
            name=conv("ck_i_image_assets_valid_status"),
        ),
        CheckConstraint(
            "media_bucket IN ('generated_images', 'edited_images')",
            name=conv("ck_i_image_assets_valid_media_bucket"),
        ),
        CheckConstraint(
            "origin_context IN ('i_direct', 'k_handoff')",
            name=conv("ck_i_image_assets_valid_origin_context"),
        ),
        UniqueConstraint("image_id", name="uq_i_image_assets_image_id"),
        Index(
            "ix_i_image_assets_scope_updated",
            "workspace_key",
            "business_context",
            "updated_at",
        ),
        Index("ix_i_image_assets_product", "product_id"),
        Index("ix_i_image_assets_variant", "variant_id"),
        Index("ix_i_image_assets_status", "status"),
        Index("ix_i_image_assets_source", "source_type"),
    )

    image_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workspace_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default=DEFAULT_WORKSPACE_KEY,
        server_default=DEFAULT_WORKSPACE_KEY,
    )
    business_context: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default=DEFAULT_BUSINESS_CONTEXT,
        server_default=DEFAULT_BUSINESS_CONTEXT,
    )
    scope_mode: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=DEFAULT_SCOPE_MODE,
        server_default=DEFAULT_SCOPE_MODE,
    )
    organization_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default=TARGET_ORGANIZATION_NAME,
        server_default=TARGET_ORGANIZATION_NAME,
    )
    product_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    variant_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SOURCE_GENERATE,
        server_default=SOURCE_GENERATE,
    )
    origin_context: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ORIGIN_I_DIRECT,
        server_default=ORIGIN_I_DIRECT,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=STATUS_STORED,
        server_default=STATUS_STORED,
    )
    media_bucket: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=MEDIA_BUCKET_GENERATED,
        server_default=MEDIA_BUCKET_GENERATED,
    )
    prompt_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_prompt_enhanced: Mapped[str] = mapped_column(Text, nullable=False)
    style_config_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    aspect_ratio: Mapped[str | None] = mapped_column(String(32), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    storage_provider: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="local_filesystem",
        server_default="local_filesystem",
    )
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    width: Mapped[int | None] = mapped_column(nullable=True)
    height: Mapped[int | None] = mapped_column(nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    metadata_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    removed_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class IImageGenerationEvent(IUUIDPrimaryKeyMixin, ITimestampMixin, Base):
    __tablename__ = "i_image_system_generation_events"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('generate', 'edit')",
            name=conv("ck_i_image_events_valid_source_type"),
        ),
        CheckConstraint(
            "status IN ('TEMP', 'PROCESSING', 'GENERATED', 'STORED', 'REMOVED')",
            name=conv("ck_i_image_events_valid_status"),
        ),
        Index(
            "ix_i_image_events_scope_created",
            "workspace_key",
            "business_context",
            "created_at",
        ),
        Index("ix_i_image_events_product", "product_id"),
        Index("ix_i_image_events_variant", "variant_id"),
        Index("ix_i_image_events_status", "status"),
    )

    workspace_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default=DEFAULT_WORKSPACE_KEY,
        server_default=DEFAULT_WORKSPACE_KEY,
    )
    business_context: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default=DEFAULT_BUSINESS_CONTEXT,
        server_default=DEFAULT_BUSINESS_CONTEXT,
    )
    scope_mode: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=DEFAULT_SCOPE_MODE,
        server_default=DEFAULT_SCOPE_MODE,
    )
    organization_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default=TARGET_ORGANIZATION_NAME,
        server_default=TARGET_ORGANIZATION_NAME,
    )
    product_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    variant_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=STATUS_PROCESSING,
        server_default=STATUS_PROCESSING,
    )
    prompt_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_prompt_enhanced: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_config_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    aspect_ratio: Mapped[str | None] = mapped_column(String(32), nullable=True)
    generation_count: Mapped[int] = mapped_column(nullable=False, default=1)
    reference_image_count: Mapped[int] = mapped_column(nullable=False, default=0)
    candidate_count: Mapped[int] = mapped_column(nullable=False, default=0)
    stored_asset_ids_json: Mapped[Any | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


__all__ = [
    "IImageAsset",
    "IImageGenerationEvent",
    "MEDIA_BUCKET_EDITED",
    "MEDIA_BUCKET_GENERATED",
    "ORIGIN_I_DIRECT",
    "ORIGIN_K_HANDOFF",
    "SOURCE_EDIT",
    "SOURCE_GENERATE",
    "STATUS_GENERATED",
    "STATUS_PROCESSING",
    "STATUS_REMOVED",
    "STATUS_STORED",
    "STATUS_TEMP",
]
