"""ra framework schema

Revision ID: 20260705_01_ra_framework_schema
Revises: 20260703_02_rw_realtime_deepseek
Create Date: 2026-07-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260705_01_ra_framework_schema"
down_revision = "20260703_02_rw_realtime_deepseek"
branch_labels = None
depends_on = None


def _json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _json_default() -> sa.TextClause:
    return sa.text("'{}'")


def _created_at_column() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def _updated_at_column() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def _id_column(name: str = "id") -> sa.Column:
    return sa.Column(name, sa.String(length=36), nullable=False)


def upgrade() -> None:
    op.create_table(
        "ra_selection_runs",
        _id_column("run_id"),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("triggered_by", sa.String(length=80), nullable=True),
        sa.Column("filters", _json_type(), nullable=False, server_default=_json_default()),
        sa.Column("counts", _json_type(), nullable=False, server_default=_json_default()),
        sa.Column("runtime_mode", sa.String(length=40), nullable=False, server_default="framework_only"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.PrimaryKeyConstraint("run_id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_selection_runs_org_status",
        "ra_selection_runs",
        ["org_id", "status"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_selection_runs_channel",
        "ra_selection_runs",
        ["channel"],
        if_not_exists=True,
    )

    op.create_table(
        "ra_candidates",
        _id_column(),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("source_asin", sa.String(length=20), nullable=False),
        sa.Column("marketplace", sa.String(length=20), nullable=False, server_default="US"),
        sa.Column("source_state", sa.String(length=40), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("title_zh", sa.Text(), nullable=True),
        sa.Column("channel_hint", sa.String(length=32), nullable=True),
        sa.Column("candidate_status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("snapshot", _json_type(), nullable=False, server_default=_json_default()),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _created_at_column(),
        _updated_at_column(),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_candidates_org_status",
        "ra_candidates",
        ["org_id", "candidate_status"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_candidates_source_asin",
        "ra_candidates",
        ["source_asin"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_candidates_run_id",
        "ra_candidates",
        ["run_id"],
        if_not_exists=True,
    )

    op.create_table(
        "ra_ai_evaluations",
        _id_column(),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("candidate_id", sa.String(length=36), nullable=True),
        sa.Column("asin", sa.String(length=20), nullable=True),
        sa.Column("layer", sa.String(length=32), nullable=False),
        sa.Column("model_role", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(length=32), nullable=True),
        sa.Column("skill_version", sa.String(length=40), nullable=True),
        sa.Column("skill_hash", sa.String(length=64), nullable=True),
        sa.Column("payload", _json_type(), nullable=False, server_default=_json_default()),
        sa.Column("in_tokens", sa.Integer(), nullable=True),
        sa.Column("out_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=True),
        _created_at_column(),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_ai_evaluations_run_layer",
        "ra_ai_evaluations",
        ["run_id", "layer"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_ai_evaluations_asin",
        "ra_ai_evaluations",
        ["asin"],
        if_not_exists=True,
    )

    op.create_table(
        "ra_supplier_searches",
        _id_column(),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("candidate_id", sa.String(length=36), nullable=True),
        sa.Column("asin", sa.String(length=20), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False, server_default="serper"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", _json_type(), nullable=False, server_default=_json_default()),
        _created_at_column(),
        _updated_at_column(),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_supplier_searches_org_status",
        "ra_supplier_searches",
        ["org_id", "status"],
        if_not_exists=True,
    )

    op.create_table(
        "ra_supplier_offers",
        _id_column(),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("search_id", sa.String(length=36), nullable=True),
        sa.Column("candidate_id", sa.String(length=36), nullable=True),
        sa.Column("asin", sa.String(length=20), nullable=True),
        sa.Column("supplier_name", sa.Text(), nullable=True),
        sa.Column("supplier_url", sa.Text(), nullable=True),
        sa.Column("unit_price_cny", sa.Numeric(10, 2), nullable=True),
        sa.Column("moq", sa.Integer(), nullable=True),
        sa.Column("rating", sa.Numeric(4, 2), nullable=True),
        sa.Column("match_score", sa.Integer(), nullable=True),
        sa.Column("offer_status", sa.String(length=32), nullable=False, server_default="candidate"),
        sa.Column("payload", _json_type(), nullable=False, server_default=_json_default()),
        _created_at_column(),
        _updated_at_column(),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_supplier_offers_candidate",
        "ra_supplier_offers",
        ["candidate_id", "offer_status"],
        if_not_exists=True,
    )

    op.create_table(
        "ra_profit_snapshots",
        _id_column(),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=True),
        sa.Column("asin", sa.String(length=20), nullable=True),
        sa.Column("sell_price_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("landed_cost_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("amazon_fees_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("net_profit_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("net_margin", sa.Numeric(6, 4), nullable=True),
        sa.Column("roi", sa.Numeric(6, 4), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("payload", _json_type(), nullable=False, server_default=_json_default()),
        _created_at_column(),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_profit_snapshots_candidate",
        "ra_profit_snapshots",
        ["candidate_id"],
        if_not_exists=True,
    )

    op.create_table(
        "ra_final_decisions",
        _id_column(),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("candidate_id", sa.String(length=36), nullable=True),
        sa.Column("asin", sa.String(length=20), nullable=True),
        sa.Column("final_score", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(length=32), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=True),
        sa.Column("barrier_type", sa.String(length=32), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("payload", _json_type(), nullable=False, server_default=_json_default()),
        _created_at_column(),
        _updated_at_column(),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_final_decisions_run",
        "ra_final_decisions",
        ["run_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_final_decisions_verdict",
        "ra_final_decisions",
        ["verdict"],
        if_not_exists=True,
    )

    op.create_table(
        "ra_reports",
        _id_column("report_id"),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("candidate_id", sa.String(length=36), nullable=True),
        sa.Column("asin", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("payload", _json_type(), nullable=False, server_default=_json_default()),
        _created_at_column(),
        _updated_at_column(),
        sa.PrimaryKeyConstraint("report_id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_reports_status",
        "ra_reports",
        ["status"],
        if_not_exists=True,
    )

    op.create_table(
        "ra_alerts",
        _id_column(),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False, server_default="info"),
        sa.Column("alert_type", sa.String(length=60), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", _json_type(), nullable=False, server_default=_json_default()),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_ra_alerts_org_severity",
        "ra_alerts",
        ["org_id", "severity"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_ra_alerts_org_severity", table_name="ra_alerts", if_exists=True)
    op.drop_table("ra_alerts", if_exists=True)
    op.drop_index("ix_ra_reports_status", table_name="ra_reports", if_exists=True)
    op.drop_table("ra_reports", if_exists=True)
    op.drop_index("ix_ra_final_decisions_verdict", table_name="ra_final_decisions", if_exists=True)
    op.drop_index("ix_ra_final_decisions_run", table_name="ra_final_decisions", if_exists=True)
    op.drop_table("ra_final_decisions", if_exists=True)
    op.drop_index("ix_ra_profit_snapshots_candidate", table_name="ra_profit_snapshots", if_exists=True)
    op.drop_table("ra_profit_snapshots", if_exists=True)
    op.drop_index("ix_ra_supplier_offers_candidate", table_name="ra_supplier_offers", if_exists=True)
    op.drop_table("ra_supplier_offers", if_exists=True)
    op.drop_index("ix_ra_supplier_searches_org_status", table_name="ra_supplier_searches", if_exists=True)
    op.drop_table("ra_supplier_searches", if_exists=True)
    op.drop_index("ix_ra_ai_evaluations_asin", table_name="ra_ai_evaluations", if_exists=True)
    op.drop_index("ix_ra_ai_evaluations_run_layer", table_name="ra_ai_evaluations", if_exists=True)
    op.drop_table("ra_ai_evaluations", if_exists=True)
    op.drop_index("ix_ra_candidates_run_id", table_name="ra_candidates", if_exists=True)
    op.drop_index("ix_ra_candidates_source_asin", table_name="ra_candidates", if_exists=True)
    op.drop_index("ix_ra_candidates_org_status", table_name="ra_candidates", if_exists=True)
    op.drop_table("ra_candidates", if_exists=True)
    op.drop_index("ix_ra_selection_runs_channel", table_name="ra_selection_runs", if_exists=True)
    op.drop_index("ix_ra_selection_runs_org_status", table_name="ra_selection_runs", if_exists=True)
    op.drop_table("ra_selection_runs", if_exists=True)

