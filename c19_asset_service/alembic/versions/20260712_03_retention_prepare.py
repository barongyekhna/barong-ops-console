"""Add a non-destructive retention prepare fence.

Revision ID: c19_asset_20260712_03
Revises: c19_asset_20260712_02
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c19_asset_20260712_03"
down_revision: str | None = "c19_asset_20260712_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chat_assets") as batch:
        batch.add_column(
            sa.Column("retention_operation_id", sa.String(length=36), nullable=True)
        )
        batch.add_column(
            sa.Column("retention_record_id", sa.String(length=36), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "retention_conversation_id", sa.String(length=128), nullable=True
            )
        )
        batch.add_column(
            sa.Column(
                "retention_prepared_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch.create_check_constraint(
            op.f("ck_chat_assets_retention_preparation_consistent"),
            "(retention_operation_id is null and retention_record_id is null "
            "and retention_conversation_id is null and retention_prepared_at is null) "
            "or (retention_operation_id is not null and retention_record_id is not null "
            "and retention_conversation_id is not null and retention_prepared_at is not null)",
        )
        batch.create_unique_constraint(
            "uq_chat_assets_retention_operation_id", ["retention_operation_id"]
        )
        batch.create_index(
            "ix_chat_assets_retention_prepared_at",
            ["retention_prepared_at"],
            unique=False,
        )


def downgrade() -> None:
    connection = op.get_bind()
    prepared = int(
        connection.execute(
            sa.text(
                "select count(*) from chat_assets "
                "where retention_operation_id is not null"
            )
        ).scalar_one()
    )
    if prepared:
        raise RuntimeError(
            "Refusing to downgrade C19 Asset v3 while retention preparations exist"
        )
    with op.batch_alter_table("chat_assets") as batch:
        batch.drop_index("ix_chat_assets_retention_prepared_at")
        batch.drop_constraint(
            "uq_chat_assets_retention_operation_id", type_="unique"
        )
        batch.drop_constraint(
            op.f("ck_chat_assets_retention_preparation_consistent"), type_="check"
        )
        batch.drop_column("retention_prepared_at")
        batch.drop_column("retention_conversation_id")
        batch.drop_column("retention_record_id")
        batch.drop_column("retention_operation_id")
