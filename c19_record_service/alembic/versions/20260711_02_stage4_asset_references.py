"""Add provider-neutral Stage 4 asset references.

Revision ID: c19_record_20260711_02
Revises: c19_record_20260711_01
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c19_record_20260711_02"
down_revision: str | None = "c19_record_20260711_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chat_records") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_chat_records_content_type_supported"), type_="check"
        )
        batch_op.create_check_constraint(
            op.f("ck_chat_records_content_type_supported"),
            "content_type in ('text', 'emoji', 'image', 'file')",
        )

    with op.batch_alter_table("record_idempotency_ledger") as batch_op:
        batch_op.add_column(
            sa.Column(
                "intent_version",
                sa.Integer(),
                server_default=sa.text("1"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            op.f("ck_record_idempotency_ledger_intent_version_supported"),
            "intent_version in (1, 2)",
        )

    op.create_table(
        "record_asset_references",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("client_asset_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256_hex", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind in ('image', 'file')",
            name=op.f("ck_record_asset_references_kind_supported"),
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name=op.f("ck_record_asset_references_ordinal_nonnegative"),
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name=op.f("ck_record_asset_references_size_bytes_positive"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_record_asset_references_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["chat_records.id"],
            name=op.f("fk_record_asset_references_record_id_chat_records"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_record_asset_references")),
        sa.UniqueConstraint(
            "record_id",
            "asset_id",
            name="uq_record_asset_references_record_asset",
        ),
        sa.UniqueConstraint(
            "record_id",
            "ordinal",
            name="uq_record_asset_references_record_ordinal",
        ),
    )
    op.create_index(
        "ix_record_asset_references_asset_id",
        "record_asset_references",
        ["asset_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_record_asset_references_asset_id",
        table_name="record_asset_references",
    )
    op.drop_table("record_asset_references")

    with op.batch_alter_table("record_idempotency_ledger") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_record_idempotency_ledger_intent_version_supported"),
            type_="check",
        )
        batch_op.drop_column("intent_version")

    with op.batch_alter_table("chat_records") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_chat_records_content_type_supported"), type_="check"
        )
        batch_op.create_check_constraint(
            op.f("ck_chat_records_content_type_supported"),
            "content_type in ('text', 'emoji')",
        )
