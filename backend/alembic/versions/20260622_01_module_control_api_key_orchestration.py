"""module control and api key orchestration

Revision ID: module_api_key_orch_001
Revises: approval_list_perf_001
Create Date: 2026-06-22

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "module_api_key_orch_001"
down_revision: str | Sequence[str] | None = "approval_list_perf_001"
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
    if not _table_exists("module_control_states"):
        op.create_table(
            "module_control_states",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("module_id", sa.String(length=128), nullable=False),
            sa.Column(
                "enabled",
                sa.Boolean(),
                server_default=sa.true(),
                nullable=False,
            ),
            sa.Column(
                "runtime_status",
                sa.String(length=32),
                server_default="active",
                nullable=False,
            ),
            sa.Column("runtime_error_code", sa.String(length=128), nullable=True),
            sa.Column(
                "runtime_error_message",
                sa.String(length=1000),
                nullable=True,
            ),
            sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_by_user_id", sa.String(length=64), nullable=True),
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
                name="uq_module_control_states_org_id_module_id",
            ),
        )
    _create_index_if_missing(
        "ix_module_control_states_org_id",
        "module_control_states",
        ["org_id"],
    )
    _create_index_if_missing(
        "ix_module_control_states_module_id",
        "module_control_states",
        ["module_id"],
    )
    _create_index_if_missing(
        "ix_module_control_states_org_id_status",
        "module_control_states",
        ["org_id", "runtime_status"],
    )

    if not _table_exists("api_key_records"):
        op.create_table(
            "api_key_records",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("key_id", sa.String(length=40), nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("url", sa.String(length=500), nullable=False),
            sa.Column("encrypted_key_value", sa.Text(), nullable=False),
            sa.Column("key_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("key_hash_prefix", sa.String(length=16), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                server_default="active",
                nullable=False,
            ),
            sa.Column("created_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("updated_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "metadata",
                _json_type(),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            _created_at_column(),
            _updated_at_column(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("key_id", name="uq_api_key_records_key_id"),
        )
    _create_index_if_missing(
        "ix_api_key_records_org_id",
        "api_key_records",
        ["org_id"],
    )
    _create_index_if_missing(
        "ix_api_key_records_org_id_status",
        "api_key_records",
        ["org_id", "status"],
    )
    _create_index_if_missing(
        "ix_api_key_records_name",
        "api_key_records",
        ["name"],
    )
    _create_index_if_missing(
        "ix_api_key_records_key_fingerprint",
        "api_key_records",
        ["key_fingerprint"],
    )

    if not _table_exists("api_key_module_bindings"):
        op.create_table(
            "api_key_module_bindings",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("binding_id", sa.String(length=40), nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("module_id", sa.String(length=128), nullable=False),
            sa.Column("key_id", sa.String(length=40), nullable=False),
            sa.Column(
                "key_alias",
                sa.String(length=80),
                server_default="default",
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                server_default="active",
                nullable=False,
            ),
            sa.Column("created_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("updated_by_user_id", sa.String(length=64), nullable=True),
            _created_at_column(),
            _updated_at_column(),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "binding_id",
                name="uq_api_key_module_bindings_binding_id",
            ),
            sa.UniqueConstraint(
                "org_id",
                "module_id",
                "key_id",
                name="uq_api_key_module_bindings_org_module_key",
            ),
        )
    _create_index_if_missing(
        "ix_api_key_module_bindings_org_id",
        "api_key_module_bindings",
        ["org_id"],
    )
    _create_index_if_missing(
        "ix_api_key_module_bindings_key_id",
        "api_key_module_bindings",
        ["key_id"],
    )
    _create_index_if_missing(
        "ix_api_key_module_bindings_org_module",
        "api_key_module_bindings",
        ["org_id", "module_id"],
    )


def downgrade() -> None:
    _drop_index_if_exists(
        "ix_api_key_module_bindings_org_module",
        "api_key_module_bindings",
    )
    _drop_index_if_exists(
        "ix_api_key_module_bindings_key_id",
        "api_key_module_bindings",
    )
    _drop_index_if_exists(
        "ix_api_key_module_bindings_org_id",
        "api_key_module_bindings",
    )
    if _table_exists("api_key_module_bindings"):
        op.drop_table("api_key_module_bindings")

    _drop_index_if_exists(
        "ix_api_key_records_key_fingerprint",
        "api_key_records",
    )
    _drop_index_if_exists("ix_api_key_records_name", "api_key_records")
    _drop_index_if_exists("ix_api_key_records_org_id_status", "api_key_records")
    _drop_index_if_exists("ix_api_key_records_org_id", "api_key_records")
    if _table_exists("api_key_records"):
        op.drop_table("api_key_records")

    _drop_index_if_exists(
        "ix_module_control_states_org_id_status",
        "module_control_states",
    )
    _drop_index_if_exists(
        "ix_module_control_states_module_id",
        "module_control_states",
    )
    _drop_index_if_exists(
        "ix_module_control_states_org_id",
        "module_control_states",
    )
    if _table_exists("module_control_states"):
        op.drop_table("module_control_states")
