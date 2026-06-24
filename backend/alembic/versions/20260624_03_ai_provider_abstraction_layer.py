"""add AI provider config registry

Revision ID: ai_provider_layer_001
Revises: k_workflow_gate_002
Create Date: 2026-06-24

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "ai_provider_layer_001"
down_revision: str | Sequence[str] | None = "k_workflow_gate_002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {
        index["name"] for index in _inspector().get_indexes(table_name)
    }


def _json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _created_at_column() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def _updated_at_column() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    if not _table_exists("provider_config"):
        op.create_table(
            "provider_config",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("module_id", sa.String(length=128), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("base_url", sa.String(length=500), nullable=False),
            sa.Column("source_key_id", sa.String(length=40), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                server_default="active",
                nullable=False,
            ),
            sa.Column(
                "metadata",
                _json_type(),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            _created_at_column(),
            _updated_at_column(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "org_id",
                "module_id",
                "provider",
                name="uq_provider_config_org_module_provider",
            ),
        )
    _create_index_if_missing(
        "ix_provider_config_org_id",
        "provider_config",
        ["org_id"],
    )
    _create_index_if_missing(
        "ix_provider_config_org_module",
        "provider_config",
        ["org_id", "module_id"],
    )
    _create_index_if_missing(
        "ix_provider_config_provider_status",
        "provider_config",
        ["provider", "status"],
    )


def downgrade() -> None:
    _drop_index_if_exists("ix_provider_config_provider_status", "provider_config")
    _drop_index_if_exists("ix_provider_config_org_module", "provider_config")
    _drop_index_if_exists("ix_provider_config_org_id", "provider_config")
    if _table_exists("provider_config"):
        op.drop_table("provider_config")
