"""PRE20-O operations and disaster recovery tables

Revision ID: pre20_o_ops_dr_001
Revises: pre20_o_concurrency_perf_001
Create Date: 2026-06-17

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "pre20_o_ops_dr_001"
down_revision: str | Sequence[str] | None = "pre20_o_concurrency_perf_001"
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


def _create_ops_alerts() -> None:
    if not _table_exists("ops_alerts"):
        op.create_table(
            "ops_alerts",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("alert_id", sa.String(length=128), nullable=False),
            sa.Column("dedupe_key", sa.String(length=300), nullable=False),
            sa.Column("source", sa.String(length=80), nullable=False),
            sa.Column("rule_id", sa.String(length=120), nullable=False),
            sa.Column("alert_type", sa.String(length=50), nullable=False),
            sa.Column("severity", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("module_id", sa.String(length=180), nullable=True),
            sa.Column("context_id", sa.String(length=180), nullable=True),
            sa.Column("trace_id", sa.String(length=180), nullable=True),
            sa.Column("title", sa.String(length=240), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("threshold_value", sa.Float(), nullable=True),
            sa.Column("observed_value", sa.Float(), nullable=True),
            sa.Column("window_seconds", sa.Integer(), nullable=False),
            sa.Column("event_count", sa.Integer(), nullable=False),
            sa.Column("payload", json_type(), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_ops_alerts")),
            sa.UniqueConstraint("alert_id", name="uq_ops_alerts_alert_id"),
            sa.UniqueConstraint("dedupe_key", name="uq_ops_alerts_dedupe_key"),
        )
    for index_name, columns in (
        ("ix_ops_alerts_org_id", ["org_id"]),
        ("ix_ops_alerts_org_id_status", ["org_id", "status"]),
        ("ix_ops_alerts_org_id_severity", ["org_id", "severity"]),
        ("ix_ops_alerts_org_id_rule_id", ["org_id", "rule_id"]),
        ("ix_ops_alerts_org_id_module_id", ["org_id", "module_id"]),
        ("ix_ops_alerts_org_id_created_at", ["org_id", "created_at"]),
    ):
        _create_index(index_name, "ops_alerts", columns)
    _create_index("ix_ops_alerts_dedupe_key", "ops_alerts", ["dedupe_key"], unique=True)


def _create_ops_alert_deliveries() -> None:
    if not _table_exists("ops_alert_deliveries"):
        op.create_table(
            "ops_alert_deliveries",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("delivery_id", sa.String(length=128), nullable=False),
            sa.Column("alert_id", sa.String(length=128), nullable=False),
            sa.Column("sink_type", sa.String(length=50), nullable=False),
            sa.Column("sink_target", sa.String(length=500), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("attempt", sa.Integer(), nullable=False),
            sa.Column("response_code", sa.Integer(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("payload", json_type(), nullable=False),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            created_at_column(),
            sa.ForeignKeyConstraint(
                ["alert_id"],
                ["ops_alerts.alert_id"],
                name=op.f("fk_ops_alert_deliveries_alert_id_ops_alerts"),
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_ops_alert_deliveries")),
            sa.UniqueConstraint(
                "delivery_id",
                name="uq_ops_alert_deliveries_delivery_id",
            ),
        )
    for index_name, columns in (
        ("ix_ops_alert_deliveries_org_id", ["org_id"]),
        ("ix_ops_alert_deliveries_org_id_alert_id", ["org_id", "alert_id"]),
        ("ix_ops_alert_deliveries_org_id_sink_type", ["org_id", "sink_type"]),
        ("ix_ops_alert_deliveries_org_id_status", ["org_id", "status"]),
        ("ix_ops_alert_deliveries_created_at", ["created_at"]),
    ):
        _create_index(index_name, "ops_alert_deliveries", columns)


def upgrade() -> None:
    _create_ops_alerts()
    _create_ops_alert_deliveries()


def downgrade() -> None:
    for table_name in (
        "ops_alert_deliveries",
        "ops_alerts",
    ):
        if _table_exists(table_name):
            op.drop_table(table_name)
