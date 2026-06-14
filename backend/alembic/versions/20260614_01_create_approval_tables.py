"""create approval persistence tables

Revision ID: c12d_approval_001
Revises: c05b_permissions_001
Create Date: 2026-06-14

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c12d_approval_001"
down_revision: str | Sequence[str] | None = "c05b_permissions_001"
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


def bigint_pk_column() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False)


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("approval_id", sa.String(length=128), nullable=False),
        sa.Column("execution_id", sa.String(length=128), nullable=False),
        sa.Column("module_key", sa.String(length=128), nullable=False),
        sa.Column("adapter_key", sa.String(length=180), nullable=False),
        sa.Column("action_key", sa.String(length=180), nullable=False),
        sa.Column("requester_id", sa.BigInteger(), nullable=False),
        sa.Column("request_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("risk_level", sa.String(length=50), nullable=False),
        sa.Column("execution_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.BigInteger(), nullable=True),
        sa.Column("context_snapshot", json_type(), nullable=False),
        sa.Column("status_trace", json_type(), nullable=False),
        sa.Column("request_payload", json_type(), nullable=False),
        bigint_pk_column(),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name=op.f("ck_approval_requests_valid_risk_level"),
        ),
        sa.CheckConstraint(
            "execution_type IN ('mock', 'no_op', 'async', 'real')",
            name=op.f("ck_approval_requests_valid_execution_type"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'auto_approved')",
            name=op.f("ck_approval_requests_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
            name=op.f("fk_approval_requests_requester_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["users.id"],
            name=op.f("fk_approval_requests_reviewer_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_requests")),
        sa.UniqueConstraint(
            "approval_id",
            name=op.f("uq_approval_requests_approval_id"),
        ),
    )
    op.create_index(
        op.f("ix_approval_requests_execution_id"),
        "approval_requests",
        ["execution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_approval_requests_requester_id"),
        "approval_requests",
        ["requester_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_approval_requests_status"),
        "approval_requests",
        ["status"],
        unique=False,
    )

    op.create_table(
        "approval_workflows",
        sa.Column("workflow_id", sa.String(length=180), nullable=False),
        sa.Column("approval_id", sa.String(length=128), nullable=False),
        sa.Column("execution_id", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=50), nullable=False),
        sa.Column(
            "workflow_created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "workflow_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("workflow_payload", json_type(), nullable=False),
        bigint_pk_column(),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "state IN ('pending', 'approved', 'rejected', 'auto_approved')",
            name=op.f("ck_approval_workflows_valid_state"),
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["approval_requests.approval_id"],
            name=op.f("fk_approval_workflows_approval_id_approval_requests"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_workflows")),
        sa.UniqueConstraint(
            "workflow_id",
            name=op.f("uq_approval_workflows_workflow_id"),
        ),
        sa.UniqueConstraint(
            "approval_id",
            name=op.f("uq_approval_workflows_approval_id"),
        ),
    )
    op.create_index(
        op.f("ix_approval_workflows_state"),
        "approval_workflows",
        ["state"],
        unique=False,
    )

    op.create_table(
        "approval_decisions",
        sa.Column("decision_id", sa.String(length=128), nullable=False),
        sa.Column("approval_id", sa.String(length=128), nullable=False),
        sa.Column("workflow_id", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decision_source", sa.String(length=50), nullable=False),
        sa.Column("actor_type", sa.String(length=50), nullable=False),
        sa.Column("actor_role", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_payload", json_type(), nullable=False),
        bigint_pk_column(),
        created_at_column(),
        sa.CheckConstraint(
            "status IN ('approved', 'rejected', 'auto_approved', 'pending')",
            name=op.f("ck_approval_decisions_valid_status"),
        ),
        sa.CheckConstraint(
            "decision_source IN ('risk', 'execution', 'module', 'user', 'global')",
            name=op.f("ck_approval_decisions_valid_source"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'system')",
            name=op.f("ck_approval_decisions_valid_actor_type"),
        ),
        sa.CheckConstraint(
            "actor_role IN ('owner', 'admin', 'user', 'system')",
            name=op.f("ck_approval_decisions_valid_actor_role"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_approval_decisions_actor_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["approval_requests.approval_id"],
            name=op.f("fk_approval_decisions_approval_id_approval_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["approval_workflows.workflow_id"],
            name=op.f("fk_approval_decisions_workflow_id_approval_workflows"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_decisions")),
        sa.UniqueConstraint(
            "decision_id",
            name=op.f("uq_approval_decisions_decision_id"),
        ),
    )
    op.create_index(
        op.f("ix_approval_decisions_approval_id"),
        "approval_decisions",
        ["approval_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_approval_decisions_workflow_id"),
        "approval_decisions",
        ["workflow_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_approval_decisions_workflow_id"),
        table_name="approval_decisions",
    )
    op.drop_index(
        op.f("ix_approval_decisions_approval_id"),
        table_name="approval_decisions",
    )
    op.drop_table("approval_decisions")
    op.drop_index(
        op.f("ix_approval_workflows_state"),
        table_name="approval_workflows",
    )
    op.drop_table("approval_workflows")
    op.drop_index(
        op.f("ix_approval_requests_status"),
        table_name="approval_requests",
    )
    op.drop_index(
        op.f("ix_approval_requests_requester_id"),
        table_name="approval_requests",
    )
    op.drop_index(
        op.f("ix_approval_requests_execution_id"),
        table_name="approval_requests",
    )
    op.drop_table("approval_requests")
