"""W-S logistics hub — Woo template sync, orders, and shipment tracking

Revision ID: 20260714_01_w_logistics_hub
Revises: 20260713_03_f_category_experience
Create Date: 2026-07-14
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260714_01_w_logistics_hub"
down_revision: str | Sequence[str] | None = "20260713_03_f_category_experience"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLASSES = "w_shipping_classes"
SYNC_JOBS = "w_sync_jobs"
ORDERS = "w_orders"


def upgrade() -> None:
    op.add_column(CLASSES, sa.Column("description", sa.Text(), nullable=True))
    op.add_column(CLASSES, sa.Column("zone_rates_json", sa.JSON(), nullable=True))
    op.add_column(
        CLASSES,
        sa.Column(
            "sync_status",
            sa.String(length=20),
            nullable=False,
            server_default="draft",
        ),
    )
    op.add_column(CLASSES, sa.Column("woo_class_id", sa.Integer(), nullable=True))
    op.add_column(
        CLASSES,
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(CLASSES, sa.Column("sync_error", sa.Text(), nullable=True))

    op.create_table(
        SYNC_JOBS,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_w_sync_jobs_job_id"),
    )
    op.create_index("ix_w_sync_jobs_status", SYNC_JOBS, ["status"])
    op.create_index(
        "ix_w_sync_jobs_target",
        SYNC_JOBS,
        ["target_type", "target_id"],
    )

    op.create_table(
        ORDERS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("woo_order_id", sa.Integer(), nullable=False),
        sa.Column("order_number", sa.String(length=64), nullable=False),
        sa.Column("woo_status", sa.String(length=30), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column("country", sa.String(length=8), nullable=True),
        sa.Column("total", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("items_json", sa.JSON(), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tracking_number", sa.String(length=128), nullable=True),
        sa.Column("carrier_code", sa.Integer(), nullable=True),
        sa.Column(
            "tracking_status",
            sa.String(length=30),
            nullable=False,
            server_default="none",
        ),
        sa.Column("tracking_events_json", sa.JSON(), nullable=True),
        sa.Column(
            "tracking_registered",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "last_tracking_update",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "writeback_status",
            sa.String(length=20),
            nullable=False,
            server_default="none",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("woo_order_id", name="uq_w_orders_woo_order_id"),
    )
    op.create_index("ix_w_orders_tracking_status", ORDERS, ["tracking_status"])
    op.create_index("ix_w_orders_tracking_number", ORDERS, ["tracking_number"])
    op.create_index("ix_w_orders_woo_status", ORDERS, ["woo_status"])
    op.create_index("ix_w_orders_placed_at", ORDERS, ["placed_at"])


def downgrade() -> None:
    op.drop_index("ix_w_orders_placed_at", table_name=ORDERS)
    op.drop_index("ix_w_orders_woo_status", table_name=ORDERS)
    op.drop_index("ix_w_orders_tracking_number", table_name=ORDERS)
    op.drop_index("ix_w_orders_tracking_status", table_name=ORDERS)
    op.drop_table(ORDERS)

    op.drop_index("ix_w_sync_jobs_target", table_name=SYNC_JOBS)
    op.drop_index("ix_w_sync_jobs_status", table_name=SYNC_JOBS)
    op.drop_table(SYNC_JOBS)

    op.drop_column(CLASSES, "sync_error")
    op.drop_column(CLASSES, "synced_at")
    op.drop_column(CLASSES, "woo_class_id")
    op.drop_column(CLASSES, "sync_status")
    op.drop_column(CLASSES, "zone_rates_json")
    op.drop_column(CLASSES, "description")
