"""A 系列(amz.ops)A0 表:店铺、店铺授权、作业、种子导入台账、汇率、每日搜索词、交易一览。

家规 14:这些表没有任何一列叫 org_id(C18G 会按会话组织自动过滤);法人列叫 company_org_id,
数据主键是 store_code。纯增量:只建新表,不动现有表;to_regclass 幂等。

Revision ID: 20260915_01_amz_tables
Revises: 20260911_03_rd_remote_desktop
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260915_01_amz_tables"
down_revision = "20260911_03_rd_remote_desktop"
branch_labels = None
depends_on = None

TABLES = (
    "amz_transactions",
    "amz_ad_search_terms",
    "amz_fx_rates",
    "amz_seed_imports",
    "amz_jobs",
    "amz_store_grants",
    "amz_stores",
)


def _table_exists(conn, name: str) -> bool:
    return bool(conn.exec_driver_sql("SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}).scalar())


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _money(name: str) -> sa.Column:
    return sa.Column(name, sa.Numeric(12, 2), nullable=False, server_default="0")


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "amz_stores"):
        op.create_table(
            "amz_stores",
            sa.Column("store_code", sa.String(length=16), primary_key=True),
            sa.Column(
                "company_org_id",
                sa.String(length=40),
                sa.ForeignKey("organizations.org_id", name="fk_amz_stores_company_org"),
                nullable=False,
            ),
            sa.Column("company_name", sa.String(length=255), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("marketplace_id", sa.String(length=32), nullable=False),
            sa.Column("region", sa.String(length=4), nullable=False),
            sa.Column("country", sa.String(length=4), nullable=False),
            sa.Column("seller_id", sa.String(length=64), nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("timezone", sa.String(length=64), nullable=False, server_default="America/Los_Angeles"),
            sa.Column("user_agent", sa.String(length=255), nullable=True),
            sa.Column("egress_ip", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
            sa.Column("metadata", _json(), nullable=False, server_default=sa.text("'{}'::jsonb") if conn.dialect.name == "postgresql" else "{}"),
            *_stamps(),
        )
        op.create_index("ix_amz_stores_company_org_id", "amz_stores", ["company_org_id"])

    if not _table_exists(conn, "amz_store_grants"):
        op.create_table(
            "amz_store_grants",
            sa.Column("user_id", sa.BigInteger(), primary_key=True),
            sa.Column(
                "store_code",
                sa.String(length=16),
                sa.ForeignKey("amz_stores.store_code", name="fk_amz_store_grants_store", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("granted_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.CheckConstraint("role IN ('view','operate','grant')", name="ck_amz_store_grants_role"),
        )

    if not _table_exists(conn, "amz_jobs"):
        op.create_table(
            "amz_jobs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "store_code",
                sa.String(length=16),
                sa.ForeignKey("amz_stores.store_code", name="fk_amz_jobs_store", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("job_type", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("run_after", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("payload", _json(), nullable=False, server_default=sa.text("'{}'::jsonb") if conn.dialect.name == "postgresql" else "{}"),
            *_stamps(),
        )
        op.create_index("ix_amz_jobs_status_run_after", "amz_jobs", ["status", "run_after"])
        op.create_index("ix_amz_jobs_store_job", "amz_jobs", ["store_code", "job_type"])
        if conn.dialect.name == "postgresql":
            op.create_index(
                "uq_amz_jobs_active_store_job",
                "amz_jobs",
                ["store_code", "job_type"],
                unique=True,
                postgresql_where=sa.text("status IN ('pending','running')"),
            )

    if not _table_exists(conn, "amz_seed_imports"):
        op.create_table(
            "amz_seed_imports",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("store_code", sa.String(length=16), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("rows", sa.Integer(), nullable=False),
            sa.Column("checksum", sa.String(length=64), nullable=False),
            sa.Column("details", _json(), nullable=False, server_default=sa.text("'{}'::jsonb") if conn.dialect.name == "postgresql" else "{}"),
            sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("checksum", name="uq_amz_seed_imports_checksum"),
        )

    if not _table_exists(conn, "amz_fx_rates"):
        op.create_table(
            "amz_fx_rates",
            sa.Column("rate_date", sa.Date(), primary_key=True),
            sa.Column("base", sa.String(length=3), primary_key=True),
            sa.Column("quote", sa.String(length=3), primary_key=True),
            sa.Column("rate", sa.Numeric(14, 6), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )

    if not _table_exists(conn, "amz_ad_search_terms"):
        op.create_table(
            "amz_ad_search_terms",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "store_code",
                sa.String(length=16),
                sa.ForeignKey("amz_stores.store_code", name="fk_amz_ad_search_terms_store"),
                nullable=False,
            ),
            sa.Column("report_date", sa.Date(), nullable=False),
            sa.Column("portfolio_name", sa.String(length=255), nullable=True),
            sa.Column("campaign_name", sa.String(length=255), nullable=False),
            sa.Column("adgroup_name", sa.String(length=255), nullable=False),
            sa.Column("targeting", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("match_type", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("search_term", sa.Text(), nullable=False),
            sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cpc", sa.Numeric(10, 4), nullable=True),
            _money("spend"),
            _money("sales_7d"),
            sa.Column("orders_7d", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("units_7d", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("same_sku_units_7d", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("other_sku_units_7d", sa.Integer(), nullable=False, server_default="0"),
            _money("same_sku_sales_7d"),
            _money("other_sku_sales_7d"),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("source", sa.String(length=16), nullable=False, server_default="seed"),
            sa.Column("row_key", sa.String(length=64), nullable=False),
            sa.UniqueConstraint("row_key", name="uq_amz_ad_search_terms_row_key"),
        )
        op.create_index("ix_amz_ad_search_terms_store_date", "amz_ad_search_terms", ["store_code", "report_date"])
        op.create_index("ix_amz_ad_search_terms_store_campaign", "amz_ad_search_terms", ["store_code", "campaign_name"])

    if not _table_exists(conn, "amz_transactions"):
        op.create_table(
            "amz_transactions",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "store_code",
                sa.String(length=16),
                sa.ForeignKey("amz_stores.store_code", name="fk_amz_transactions_store"),
                nullable=False,
            ),
            sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("settlement_id", sa.String(length=32), nullable=True),
            sa.Column("txn_type", sa.String(length=64), nullable=False),
            sa.Column("order_id", sa.String(length=32), nullable=True),
            sa.Column("sku", sa.String(length=128), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("marketplace", sa.String(length=64), nullable=True),
            sa.Column("fulfillment", sa.String(length=32), nullable=True),
            _money("product_sales"),
            _money("product_sales_tax"),
            _money("shipping_credits"),
            _money("promotional_rebates"),
            _money("marketplace_withheld_tax"),
            _money("selling_fees"),
            _money("fba_fees"),
            _money("other_transaction_fees"),
            _money("other"),
            _money("total"),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("fx_rate", sa.Numeric(14, 6), nullable=False, server_default="1"),
            sa.Column("fx_source", sa.String(length=32), nullable=False, server_default="native"),
            _money("total_usd"),
            sa.Column("source", sa.String(length=16), nullable=False, server_default="seed"),
            sa.Column("row_key", sa.String(length=64), nullable=False),
            sa.UniqueConstraint("row_key", name="uq_amz_transactions_row_key"),
        )
        op.create_index("ix_amz_transactions_store_posted", "amz_transactions", ["store_code", "posted_at"])
        op.create_index("ix_amz_transactions_store_type", "amz_transactions", ["store_code", "txn_type"])


def downgrade() -> None:
    conn = op.get_bind()
    for name in TABLES:
        if _table_exists(conn, name):
            op.drop_table(name)
