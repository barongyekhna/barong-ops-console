"""H site health runs and findings ledger.

Revision ID: 20260715_01_h_site_health
Revises: 20260714_04_f_market_refs
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_01_h_site_health"
down_revision: str | Sequence[str] | None = "20260714_04_f_market_refs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNS = "h_health_runs"
FINDINGS = "h_health_findings"


def upgrade() -> None:
    op.create_table(
        RUNS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "trigger",
            sa.String(length=20),
            nullable=False,
            server_default="scheduled",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="running",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("urls_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("urls_ok", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("urls_broken", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("urls_slow", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_response_ms", sa.Integer(), nullable=True),
        sa.Column("p95_response_ms", sa.Integer(), nullable=True),
        sa.Column(
            "sitemap_ok",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "homepage_ok",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.CheckConstraint(
            "trigger IN ('scheduled', 'manual')",
            name="ck_h_health_runs_valid_trigger",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_h_health_runs_valid_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        FINDINGS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey(
                f"{RUNS}.id",
                name="fk_h_health_findings_run_id_runs",
            ),
            nullable=False,
        ),
        sa.Column("finding_type", sa.String(length=30), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_ms", sa.Integer(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.CheckConstraint(
            "finding_type IN ("
            "'broken_link', 'slow_page', 'sitemap_error', 'homepage_error'"
            ")",
            name="ck_h_health_findings_valid_type",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')",
            name="ck_h_health_findings_valid_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_h_health_findings_run_id",
        FINDINGS,
        ["run_id"],
    )
    op.create_index(
        "ix_h_health_findings_type_status",
        FINDINGS,
        ["finding_type", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_h_health_findings_type_status", table_name=FINDINGS)
    op.drop_index("ix_h_health_findings_run_id", table_name=FINDINGS)
    op.drop_table(FINDINGS)
    op.drop_table(RUNS)
