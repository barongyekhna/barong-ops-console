"""create I-series independent image system tables

Revision ID: i_image_system_001
Revises: k_sku_variant_001
Create Date: 2026-06-27

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "i_image_system_001"
down_revision: str | Sequence[str] | None = "k_sku_variant_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ASSETS = "i_image_system_assets"
EVENTS = "i_image_system_generation_events"


def json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def created_at_column() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def updated_at_column() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def user_trace_column(name: str) -> sa.Column:
    return sa.Column(name, sa.Uuid(), nullable=True)


def scope_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "workspace_key",
            sa.String(length=128),
            server_default="default_independent_store",
            nullable=False,
        ),
        sa.Column(
            "business_context",
            sa.String(length=128),
            server_default="independent_store",
            nullable=False,
        ),
        sa.Column(
            "scope_mode",
            sa.String(length=64),
            server_default="adapter_pending",
            nullable=False,
        ),
        sa.Column(
            "organization_name",
            sa.String(length=255),
            server_default="涌龙麟（深圳）国际贸易有限公司",
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        ASSETS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("image_id", sa.String(length=128), nullable=False),
        *scope_columns(),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("variant_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(length=32), server_default="generate", nullable=False),
        sa.Column("origin_context", sa.String(length=32), server_default="i_direct", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="STORED", nullable=False),
        sa.Column(
            "media_bucket",
            sa.String(length=64),
            server_default="generated_images",
            nullable=False,
        ),
        sa.Column("prompt_original", sa.Text(), nullable=True),
        sa.Column("image_prompt_enhanced", sa.Text(), nullable=False),
        sa.Column("style_config_json", json_type(), nullable=True),
        sa.Column("aspect_ratio", sa.String(length=32), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "storage_provider",
            sa.String(length=100),
            server_default="local_filesystem",
            nullable=False,
        ),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("metadata_json", json_type(), nullable=True),
        user_trace_column("created_by_user_id"),
        user_trace_column("updated_by_user_id"),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        user_trace_column("removed_by_user_id"),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "source_type IN ('generate', 'edit')",
            name=op.f("ck_i_image_assets_valid_source_type"),
        ),
        sa.CheckConstraint(
            "status IN ('TEMP', 'PROCESSING', 'GENERATED', 'STORED', 'REMOVED')",
            name=op.f("ck_i_image_assets_valid_status"),
        ),
        sa.CheckConstraint(
            "media_bucket IN ('generated_images', 'edited_images')",
            name=op.f("ck_i_image_assets_valid_media_bucket"),
        ),
        sa.CheckConstraint(
            "origin_context IN ('i_direct', 'k_handoff')",
            name=op.f("ck_i_image_assets_valid_origin_context"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_i_image_system_assets")),
        sa.UniqueConstraint("image_id", name="uq_i_image_assets_image_id"),
    )
    op.create_index(
        "ix_i_image_assets_scope_updated",
        ASSETS,
        ["workspace_key", "business_context", "updated_at"],
    )
    op.create_index("ix_i_image_assets_product", ASSETS, ["product_id"])
    op.create_index("ix_i_image_assets_variant", ASSETS, ["variant_id"])
    op.create_index("ix_i_image_assets_status", ASSETS, ["status"])
    op.create_index("ix_i_image_assets_source", ASSETS, ["source_type"])

    op.create_table(
        EVENTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        *scope_columns(),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("variant_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PROCESSING", nullable=False),
        sa.Column("prompt_original", sa.Text(), nullable=True),
        sa.Column("image_prompt_enhanced", sa.Text(), nullable=True),
        sa.Column("style_config_json", json_type(), nullable=True),
        sa.Column("aspect_ratio", sa.String(length=32), nullable=True),
        sa.Column("generation_count", sa.Integer(), nullable=False),
        sa.Column("reference_image_count", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("stored_asset_ids_json", json_type(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", json_type(), nullable=True),
        user_trace_column("created_by_user_id"),
        user_trace_column("updated_by_user_id"),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "source_type IN ('generate', 'edit')",
            name=op.f("ck_i_image_events_valid_source_type"),
        ),
        sa.CheckConstraint(
            "status IN ('TEMP', 'PROCESSING', 'GENERATED', 'STORED', 'REMOVED')",
            name=op.f("ck_i_image_events_valid_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_i_image_system_generation_events")),
    )
    op.create_index(
        "ix_i_image_events_scope_created",
        EVENTS,
        ["workspace_key", "business_context", "created_at"],
    )
    op.create_index("ix_i_image_events_product", EVENTS, ["product_id"])
    op.create_index("ix_i_image_events_variant", EVENTS, ["variant_id"])
    op.create_index("ix_i_image_events_status", EVENTS, ["status"])


def downgrade() -> None:
    op.drop_index("ix_i_image_events_status", table_name=EVENTS)
    op.drop_index("ix_i_image_events_variant", table_name=EVENTS)
    op.drop_index("ix_i_image_events_product", table_name=EVENTS)
    op.drop_index("ix_i_image_events_scope_created", table_name=EVENTS)
    op.drop_table(EVENTS)

    op.drop_index("ix_i_image_assets_source", table_name=ASSETS)
    op.drop_index("ix_i_image_assets_status", table_name=ASSETS)
    op.drop_index("ix_i_image_assets_variant", table_name=ASSETS)
    op.drop_index("ix_i_image_assets_product", table_name=ASSETS)
    op.drop_index("ix_i_image_assets_scope_updated", table_name=ASSETS)
    op.drop_table(ASSETS)
