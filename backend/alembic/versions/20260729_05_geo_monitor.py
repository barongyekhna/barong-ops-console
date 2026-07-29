"""GEO milestone 4: terrain monitoring for buyer questions.

Watch the organic first page for the questions the guides were written to answer:
where we rank, who holds the page, and whether it is soft enough to be worth
attacking. Serper returns no AI Overview (verified 2026-07-29), so this measures
the organic results the answer engines actually draw from, rather than pretending
to read the AI answer itself.

Revision ID: 20260729_05_geo_monitor
Revises: 20260729_04_b2b_outreach
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_05_geo_monitor"
down_revision: str | Sequence[str] | None = "20260729_04_b2b_outreach"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WS = "default_independent_store"
_BC = "independent_store"
_SM = "adapter_pending"


def _scope_columns() -> list[sa.Column]:
    return [
        sa.Column("workspace_key", sa.String(length=128), nullable=False, server_default=_WS),
        sa.Column("business_context", sa.String(length=64), nullable=False, server_default=_BC),
        sa.Column("scope_mode", sa.String(length=32), nullable=False, server_default=_SM),
    ]


def _stamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    op.create_table(
        "geo_monitor_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope_columns(),
        sa.Column("cluster_id", sa.Uuid(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        *_stamp_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_geo_monitor_questions"),
        sa.ForeignKeyConstraint(
            ["cluster_id"], ["geo_content_clusters.id"],
            name="fk_geo_monitor_questions_cluster_id",
        ),
    )
    op.create_index("ix_geo_monitor_questions_cluster", "geo_monitor_questions", ["cluster_id"])
    op.create_index("ix_geo_monitor_questions_active", "geo_monitor_questions", ["is_active"])

    op.create_table(
        "geo_monitor_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope_columns(),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by_username", sa.String(length=255), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_stamp_columns(),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed', 'partial')",
            name="ck_geo_monitor_runs_valid_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_geo_monitor_runs"),
    )
    op.create_index("ix_geo_monitor_runs_created", "geo_monitor_runs", ["created_at"])

    op.create_table(
        "geo_monitor_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope_columns(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("our_position", sa.Integer(), nullable=True),
        sa.Column("attackability", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("terrain", sa.String(length=16), nullable=False, server_default="mixed"),
        sa.Column("results_json", sa.JSON(), nullable=True),
        sa.Column("holder_counts_json", sa.JSON(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        *_stamp_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_geo_monitor_results"),
        sa.ForeignKeyConstraint(["run_id"], ["geo_monitor_runs.id"], name="fk_geo_monitor_results_run_id"),
        sa.ForeignKeyConstraint(
            ["question_id"], ["geo_monitor_questions.id"],
            name="fk_geo_monitor_results_question_id",
        ),
    )
    op.create_index("ix_geo_monitor_results_run", "geo_monitor_results", ["run_id"])
    op.create_index("ix_geo_monitor_results_question", "geo_monitor_results", ["question_id"])


def downgrade() -> None:
    op.drop_index("ix_geo_monitor_results_question", table_name="geo_monitor_results")
    op.drop_index("ix_geo_monitor_results_run", table_name="geo_monitor_results")
    op.drop_table("geo_monitor_results")
    op.drop_index("ix_geo_monitor_runs_created", table_name="geo_monitor_runs")
    op.drop_table("geo_monitor_runs")
    op.drop_index("ix_geo_monitor_questions_active", table_name="geo_monitor_questions")
    op.drop_index("ix_geo_monitor_questions_cluster", table_name="geo_monitor_questions")
    op.drop_table("geo_monitor_questions")
