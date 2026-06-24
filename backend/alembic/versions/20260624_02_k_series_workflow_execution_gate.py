"""add K series workflow execution gate records

Revision ID: k_series_workflow_gate_002
Revises: k_series_product_knowledge_activation_001
Create Date: 2026-06-24

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "k_series_workflow_gate_002"
down_revision: str | Sequence[str] | None = "k_series_product_knowledge_activation_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRODUCTS = "k_product_knowledge_products"
WORKFLOW_EXECUTIONS = "k_product_knowledge_workflow_executions"
TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"


def json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def user_trace_column(name: str) -> sa.Column:
    return sa.Column(name, sa.Uuid(), nullable=True)


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


def upgrade() -> None:
    op.add_column(
        PRODUCTS,
        sa.Column(
            "organization_name",
            sa.String(length=255),
            server_default=TARGET_ORGANIZATION_NAME,
            nullable=False,
        ),
    )

    op.create_table(
        WORKFLOW_EXECUTIONS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("organization_name", sa.String(length=255), nullable=False),
        sa.Column("workspace_key", sa.String(length=128), nullable=False),
        sa.Column("business_context", sa.String(length=128), nullable=False),
        sa.Column("scope_mode", sa.String(length=64), nullable=False),
        sa.Column("target_market", sa.String(length=50), nullable=False),
        sa.Column("target_region", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="created", nullable=False),
        sa.Column("current_step", sa.String(length=100), nullable=False),
        sa.Column("trace_json", json_type(), nullable=False),
        sa.Column("chatgpt_filter_result_json", json_type(), nullable=True),
        sa.Column("claude_filter_result_json", json_type(), nullable=True),
        sa.Column("risk_approval_log_json", json_type(), nullable=True),
        sa.Column("final_keyword_set_json", json_type(), nullable=True),
        sa.Column("unit_conversion_json", json_type(), nullable=True),
        sa.Column("image_binding_json", json_type(), nullable=True),
        sa.Column("export_payloads_json", json_type(), nullable=True),
        sa.Column("execution_gate_logs_json", json_type(), nullable=False),
        sa.Column("error_report_json", json_type(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        user_trace_column("created_by_user_id"),
        user_trace_column("updated_by_user_id"),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "status IN ("
            "'created', 'running', 'blocked', 'failed', "
            "'ready_for_export', 'exported'"
            ")",
            name=op.f("ck_kpk_workflow_executions_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            [f"{PRODUCTS}.id"],
            name=op.f("fk_kpk_workflow_executions_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kpk_workflow_executions")),
    )
    op.create_index(
        op.f("ix_kpk_workflow_executions_product"),
        WORKFLOW_EXECUTIONS,
        ["product_id"],
    )
    op.create_index(
        op.f("ix_kpk_workflow_executions_status"),
        WORKFLOW_EXECUTIONS,
        ["status"],
    )
    op.create_index(
        op.f("ix_kpk_workflow_executions_current_step"),
        WORKFLOW_EXECUTIONS,
        ["current_step"],
    )
    op.create_index(
        op.f("ix_kpk_workflow_executions_scope"),
        WORKFLOW_EXECUTIONS,
        ["workspace_key", "business_context", "organization_name"],
    )
    op.create_index(
        op.f("ix_kpk_workflow_executions_created"),
        WORKFLOW_EXECUTIONS,
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_kpk_workflow_executions_created"), WORKFLOW_EXECUTIONS)
    op.drop_index(op.f("ix_kpk_workflow_executions_scope"), WORKFLOW_EXECUTIONS)
    op.drop_index(op.f("ix_kpk_workflow_executions_current_step"), WORKFLOW_EXECUTIONS)
    op.drop_index(op.f("ix_kpk_workflow_executions_status"), WORKFLOW_EXECUTIONS)
    op.drop_index(op.f("ix_kpk_workflow_executions_product"), WORKFLOW_EXECUTIONS)
    op.drop_table(WORKFLOW_EXECUTIONS)
    op.drop_column(PRODUCTS, "organization_name")
