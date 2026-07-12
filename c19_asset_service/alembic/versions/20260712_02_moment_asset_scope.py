"""Generalize asset ownership scope and add Moment-image usage.

Revision ID: c19_asset_20260712_02
Revises: c19_asset_20260711_01
Create Date: 2026-07-12

The physical object format is unchanged.  Existing chat rows and ticket hashes
are migrated in place without changing asset IDs, versions, object keys, or
binding state.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c19_asset_20260712_02"
down_revision: str | None = "c19_asset_20260711_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _upgrade_assets() -> None:
    op.add_column(
        "chat_assets", sa.Column("usage", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "chat_assets", sa.Column("scope_id", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "chat_assets",
        sa.Column("binding_client_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "chat_assets",
        sa.Column("bound_resource_id", sa.String(length=128), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE chat_assets SET usage = 'chat_message', "
            "scope_id = conversation_id, "
            "binding_client_id = client_message_id, "
            "bound_resource_id = record_id"
        )
    )
    op.drop_index("ix_chat_assets_record_id", table_name="chat_assets")
    with op.batch_alter_table("chat_assets") as batch:
        batch.drop_constraint(
            op.f("ck_chat_assets_binding_consistent"), type_="check"
        )
        batch.alter_column("usage", existing_type=sa.String(20), nullable=False)
        batch.alter_column("scope_id", existing_type=sa.String(128), nullable=False)
        batch.create_check_constraint(
            op.f("ck_chat_assets_usage_supported"),
            "usage in ('chat_message', 'moment_image')",
        )
        batch.create_check_constraint(
            op.f("ck_chat_assets_scope_id_not_blank"), "length(scope_id) > 0"
        )
        batch.create_check_constraint(
            op.f("ck_chat_assets_moment_usage_requires_image"),
            "usage <> 'moment_image' or kind = 'image'",
        )
        batch.create_check_constraint(
            op.f("ck_chat_assets_binding_consistent"),
            "(binding_status = 'unbound' and binding_client_id is null "
            "and bound_resource_id is null) or "
            "(binding_status = 'prepared' and binding_client_id is not null "
            "and bound_resource_id is null) or "
            "(binding_status = 'committed' and binding_client_id is not null "
            "and bound_resource_id is not null)",
        )
        batch.create_check_constraint(
            op.f("ck_chat_assets_moment_binding_matches_scope"),
            "usage <> 'moment_image' or binding_status <> 'committed' "
            "or bound_resource_id = scope_id",
        )
        batch.drop_column("conversation_id")
        batch.drop_column("client_message_id")
        batch.drop_column("record_id")
    op.create_index(
        "ix_chat_assets_usage_scope_binding",
        "chat_assets",
        ["usage", "scope_id", "bound_resource_id"],
        unique=False,
    )


def _upgrade_tickets() -> None:
    op.add_column(
        "asset_transfer_tickets",
        sa.Column("usage", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "asset_transfer_tickets",
        sa.Column("scope_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "asset_transfer_tickets",
        sa.Column("bound_resource_id", sa.String(length=128), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE asset_transfer_tickets SET usage = 'chat_message', "
            "scope_id = conversation_id, bound_resource_id = record_id"
        )
    )
    with op.batch_alter_table("asset_transfer_tickets") as batch:
        batch.drop_constraint(
            op.f("ck_asset_transfer_tickets_direction_fields_consistent"),
            type_="check",
        )
        batch.alter_column("usage", existing_type=sa.String(20), nullable=False)
        batch.alter_column("scope_id", existing_type=sa.String(128), nullable=False)
        batch.create_check_constraint(
            op.f("ck_asset_transfer_tickets_usage_supported"),
            "usage in ('chat_message', 'moment_image')",
        )
        batch.create_check_constraint(
            op.f("ck_asset_transfer_tickets_scope_id_not_blank"),
            "length(scope_id) > 0",
        )
        batch.create_check_constraint(
            op.f("ck_asset_transfer_tickets_direction_fields_consistent"),
            "(direction = 'upload' and reader_user_id is null "
            "and bound_resource_id is null and variant is null "
            "and disposition is null) or "
            "(direction = 'download' and reader_user_id is not null "
            "and bound_resource_id is not null "
            "and variant in ('original','thumbnail') "
            "and disposition in ('attachment','inline'))",
        )
        batch.create_check_constraint(
            op.f("ck_asset_transfer_tickets_moment_download_matches_scope"),
            "usage <> 'moment_image' or direction <> 'download' "
            "or bound_resource_id = scope_id",
        )
        batch.drop_column("conversation_id")
        batch.drop_column("record_id")


def upgrade() -> None:
    _upgrade_assets()
    _upgrade_tickets()


def _assert_downgrade_is_lossless() -> None:
    connection = op.get_bind()
    moment_assets = connection.scalar(
        sa.text("SELECT count(*) FROM chat_assets WHERE usage = 'moment_image'")
    )
    moment_tickets = connection.scalar(
        sa.text(
            "SELECT count(*) FROM asset_transfer_tickets "
            "WHERE usage = 'moment_image'"
        )
    )
    oversized_chat_ids = connection.scalar(
        sa.text(
            "SELECT count(*) FROM chat_assets WHERE usage = 'chat_message' "
            "AND bound_resource_id IS NOT NULL "
            "AND length(bound_resource_id) > 64"
        )
    )
    oversized_ticket_ids = connection.scalar(
        sa.text(
            "SELECT count(*) FROM asset_transfer_tickets "
            "WHERE usage = 'chat_message' AND bound_resource_id IS NOT NULL "
            "AND length(bound_resource_id) > 64"
        )
    )
    if any(
        int(value or 0) > 0
        for value in (
            moment_assets,
            moment_tickets,
            oversized_chat_ids,
            oversized_ticket_ids,
        )
    ):
        raise RuntimeError(
            "Asset scope downgrade would discard Moment or oversized binding data."
        )


def _downgrade_tickets() -> None:
    op.add_column(
        "asset_transfer_tickets",
        sa.Column("conversation_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "asset_transfer_tickets",
        sa.Column("record_id", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE asset_transfer_tickets SET conversation_id = scope_id, "
            "record_id = bound_resource_id WHERE usage = 'chat_message'"
        )
    )
    with op.batch_alter_table("asset_transfer_tickets") as batch:
        batch.drop_constraint(
            op.f("ck_asset_transfer_tickets_moment_download_matches_scope"),
            type_="check",
        )
        batch.drop_constraint(
            op.f("ck_asset_transfer_tickets_direction_fields_consistent"),
            type_="check",
        )
        batch.drop_constraint(
            op.f("ck_asset_transfer_tickets_scope_id_not_blank"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_asset_transfer_tickets_usage_supported"), type_="check"
        )
        batch.alter_column(
            "conversation_id", existing_type=sa.String(128), nullable=False
        )
        batch.create_check_constraint(
            op.f("ck_asset_transfer_tickets_direction_fields_consistent"),
            "(direction = 'upload' and reader_user_id is null and record_id is null "
            "and variant is null and disposition is null) or "
            "(direction = 'download' and reader_user_id is not null and record_id is not null "
            "and variant in ('original','thumbnail') and disposition in ('attachment','inline'))",
        )
        batch.drop_column("usage")
        batch.drop_column("scope_id")
        batch.drop_column("bound_resource_id")


def _downgrade_assets() -> None:
    op.add_column(
        "chat_assets",
        sa.Column("conversation_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "chat_assets",
        sa.Column("client_message_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "chat_assets", sa.Column("record_id", sa.String(length=64), nullable=True)
    )
    op.execute(
        sa.text(
            "UPDATE chat_assets SET conversation_id = scope_id, "
            "client_message_id = binding_client_id, "
            "record_id = bound_resource_id WHERE usage = 'chat_message'"
        )
    )
    op.drop_index(
        "ix_chat_assets_usage_scope_binding", table_name="chat_assets"
    )
    with op.batch_alter_table("chat_assets") as batch:
        batch.drop_constraint(
            op.f("ck_chat_assets_moment_binding_matches_scope"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_chat_assets_binding_consistent"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_chat_assets_moment_usage_requires_image"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_chat_assets_scope_id_not_blank"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_chat_assets_usage_supported"), type_="check"
        )
        batch.alter_column(
            "conversation_id", existing_type=sa.String(128), nullable=False
        )
        batch.create_check_constraint(
            op.f("ck_chat_assets_binding_consistent"),
            "(binding_status = 'unbound' and client_message_id is null and record_id is null)"
            " or (binding_status = 'prepared' and client_message_id is not null and record_id is null)"
            " or (binding_status = 'committed' and client_message_id is not null and record_id is not null)",
        )
        batch.drop_column("usage")
        batch.drop_column("scope_id")
        batch.drop_column("binding_client_id")
        batch.drop_column("bound_resource_id")
    op.create_index(
        "ix_chat_assets_record_id", "chat_assets", ["record_id"], unique=False
    )


def downgrade() -> None:
    _assert_downgrade_is_lossless()
    _downgrade_tickets()
    _downgrade_assets()
