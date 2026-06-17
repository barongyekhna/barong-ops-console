"""PRE20-Q live enable gate ops tables

Revision ID: pre20_q_live_enable_gate_001
Revises: pre20_o_ops_dr_001
Create Date: 2026-06-17

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "pre20_q_live_enable_gate_001"
down_revision: str | Sequence[str] | None = "pre20_o_ops_dr_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def _inspector() -> sa.Inspector:
    return inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {index["name"] for index in _inspector().get_indexes(table_name)}


def _create_index(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _create_live_gate_policies() -> None:
    if not _table_exists("ops_live_gate_policies"):
        op.create_table(
            "ops_live_gate_policies",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("policy_id", sa.String(length=128), nullable=False),
            sa.Column("policy_scope", sa.String(length=30), nullable=False),
            sa.Column("scope_key", sa.String(length=180), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "staging_only",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "rollout_percentage",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("allowed_orgs", json_type(), nullable=False),
            sa.Column("allowed_modules", json_type(), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("metadata", json_type(), nullable=False),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_ops_live_gate_policies")),
            sa.UniqueConstraint(
                "policy_id",
                name="uq_ops_live_gate_policies_policy_id",
            ),
        )
    _create_index(
        "ix_ops_live_gate_policies_org_id_scope",
        "ops_live_gate_policies",
        ["org_id", "policy_scope", "scope_key"],
    )
    _create_index(
        "ix_ops_live_gate_policies_org_id_status",
        "ops_live_gate_policies",
        ["org_id", "status"],
    )


def _create_unlock_tokens() -> None:
    if not _table_exists("ops_execution_unlock_tokens"):
        op.create_table(
            "ops_execution_unlock_tokens",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("unlock_id", sa.String(length=128), nullable=False),
            sa.Column("approval_id", sa.String(length=128), nullable=False),
            sa.Column("execution_id", sa.String(length=128), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("payload", json_type(), nullable=False),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint(
                "id",
                name=op.f("pk_ops_execution_unlock_tokens"),
            ),
            sa.UniqueConstraint(
                "unlock_id",
                name="uq_ops_execution_unlock_tokens_unlock_id",
            ),
        )
    _create_index(
        "ix_ops_execution_unlock_tokens_org_id_execution",
        "ops_execution_unlock_tokens",
        ["org_id", "execution_id", "status"],
    )
    _create_index(
        "ix_ops_execution_unlock_tokens_org_id_approval",
        "ops_execution_unlock_tokens",
        ["org_id", "approval_id"],
    )


def _create_canary_rollouts() -> None:
    if not _table_exists("ops_canary_rollouts"):
        op.create_table(
            "ops_canary_rollouts",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("rollout_id", sa.String(length=128), nullable=False),
            sa.Column("scope_type", sa.String(length=30), nullable=False),
            sa.Column("scope_key", sa.String(length=180), nullable=False),
            sa.Column("stage", sa.String(length=30), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("percentage", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("org_ids", json_type(), nullable=False),
            sa.Column("module_ids", json_type(), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("payload", json_type(), nullable=False),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_ops_canary_rollouts")),
            sa.UniqueConstraint(
                "rollout_id",
                name="uq_ops_canary_rollouts_rollout_id",
            ),
        )
    _create_index(
        "ix_ops_canary_rollouts_org_id_scope",
        "ops_canary_rollouts",
        ["org_id", "scope_type", "scope_key"],
    )
    _create_index(
        "ix_ops_canary_rollouts_org_id_status",
        "ops_canary_rollouts",
        ["org_id", "status"],
    )


def _create_rollback_guards() -> None:
    if not _table_exists("ops_rollback_guards"):
        op.create_table(
            "ops_rollback_guards",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("guard_id", sa.String(length=128), nullable=False),
            sa.Column("environment", sa.String(length=50), nullable=False),
            sa.Column("service", sa.String(length=80), nullable=False),
            sa.Column("current_version", sa.String(length=180), nullable=True),
            sa.Column("previous_version", sa.String(length=180), nullable=True),
            sa.Column("restored_version", sa.String(length=180), nullable=True),
            sa.Column("image_digest", sa.String(length=255), nullable=True),
            sa.Column("db_revision", sa.String(length=128), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rollback_triggered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consistency_payload", json_type(), nullable=False),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_ops_rollback_guards")),
            sa.UniqueConstraint(
                "guard_id",
                name="uq_ops_rollback_guards_guard_id",
            ),
        )
    _create_index(
        "ix_ops_rollback_guards_org_id_environment",
        "ops_rollback_guards",
        ["org_id", "environment"],
    )
    _create_index(
        "ix_ops_rollback_guards_org_id_status",
        "ops_rollback_guards",
        ["org_id", "status"],
    )
    _create_index(
        "ix_ops_rollback_guards_org_id_service",
        "ops_rollback_guards",
        ["org_id", "service"],
    )


def upgrade() -> None:
    _create_live_gate_policies()
    _create_unlock_tokens()
    _create_canary_rollouts()
    _create_rollback_guards()


def downgrade() -> None:
    for table_name in (
        "ops_rollback_guards",
        "ops_canary_rollouts",
        "ops_execution_unlock_tokens",
        "ops_live_gate_policies",
    ):
        if _table_exists(table_name):
            op.drop_table(table_name)
