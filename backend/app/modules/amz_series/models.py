"""A 系列表(A0 这一批:店铺、授权、作业、种子导入、每日搜索词、交易一览、汇率)。

家规 14:**这些表没有任何一列叫 ``org_id``。** C18G 数据隔离
(``services/data_isolation.py``)会按当前会话的组织自动过滤所有带 ``org_id`` 列的模型;
王创鑫的活跃组织是深圳,一旦带了这列,他在 A 里一条店铺数据都看不到。
法人归属列叫 ``company_org_id``,数据主键是 ``store_code``,跨店查询按调用者的授权店铺集合过滤。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from ...db.base import Base
from .constants import STORE_ROLES


def json_type() -> JSON:
    """与 ``models.base_mixins.json_type`` 同义;本地定义避开 ``backend.app.models`` 的循环导入。"""
    return JSON().with_variant(JSONB(), "postgresql")


class AmzTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AmzStore(AmzTimestampMixin, Base):
    """店铺 = 卖家账号 × 区域。``company_org_id`` 指向法人组织(org_type=amazon)。"""

    __tablename__ = "amz_stores"

    store_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    company_org_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("organizations.org_id", name="fk_amz_stores_company_org"), nullable=False, index=True
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    marketplace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    region: Mapped[str] = mapped_column(String(4), nullable=False)
    country: Mapped[str] = mapped_column(String(4), nullable=False)
    seller_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="America/Los_Angeles")
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    egress_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", json_type(), nullable=False, default=dict)


class AmzStoreGrant(Base):
    """人维度的门。只 owner 绕过;super_admin 也要有行。``role`` view < operate < grant。"""

    __tablename__ = "amz_store_grants"
    __table_args__ = (
        CheckConstraint(
            "role IN ('" + "','".join(STORE_ROLES) + "')",
            name="ck_amz_store_grants_role",
        ),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    store_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("amz_stores.store_code", name="fk_amz_store_grants_store", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    granted_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AmzJob(AmzTimestampMixin, Base):
    """按 (store, job_type) 排队的作业;worker 用 FOR UPDATE SKIP LOCKED 领。"""

    __tablename__ = "amz_jobs"
    __table_args__ = (
        Index("ix_amz_jobs_status_run_after", "status", "run_after"),
        Index("ix_amz_jobs_store_job", "store_code", "job_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    store_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("amz_stores.store_code", name="fk_amz_jobs_store", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column("payload", json_type(), nullable=False, default=dict)


class AmzSeedImport(Base):
    """种子文件导入台账(var/amazon/seed)。checksum 唯一 = 同一份文件绝不导两遍。"""

    __tablename__ = "amz_seed_imports"
    __table_args__ = (UniqueConstraint("checksum", name="uq_amz_seed_imports_checksum"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    store_code: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    rows: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column("details", json_type(), nullable=False, default=dict)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AmzFxRate(Base):
    """每日汇率。历史行按当天汇率折,永不按今天的。"""

    __tablename__ = "amz_fx_rates"

    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    base: Mapped[str] = mapped_column(String(3), primary_key=True)
    quote: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AmzAdSearchTerm(Base):
    """SP 搜索词日报,一行 = 店 × 日 × 活动 × 广告组 × 投放 × 匹配 × 搜索词。**永久保留**。"""

    __tablename__ = "amz_ad_search_terms"
    __table_args__ = (
        UniqueConstraint("row_key", name="uq_amz_ad_search_terms_row_key"),
        Index("ix_amz_ad_search_terms_store_date", "store_code", "report_date"),
        Index("ix_amz_ad_search_terms_store_campaign", "store_code", "campaign_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("amz_stores.store_code", name="fk_amz_ad_search_terms_store"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    portfolio_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False)
    adgroup_name: Mapped[str] = mapped_column(String(255), nullable=False)
    targeting: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    match_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="")
    search_term: Mapped[str] = mapped_column(Text, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cpc: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    spend: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    sales_7d: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    orders_7d: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    units_7d: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    same_sku_units_7d: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    other_sku_units_7d: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    same_sku_sales_7d: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    other_sku_sales_7d: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="seed")
    row_key: Mapped[str] = mapped_column(String(64), nullable=False)


class AmzTransaction(Base):
    """交易一览(Finances / 后台"交易"报表)。原币 + 按当天汇率折的美元。"""

    __tablename__ = "amz_transactions"
    __table_args__ = (
        UniqueConstraint("row_key", name="uq_amz_transactions_row_key"),
        Index("ix_amz_transactions_store_posted", "store_code", "posted_at"),
        Index("ix_amz_transactions_store_type", "store_code", "txn_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("amz_stores.store_code", name="fk_amz_transactions_store"), nullable=False
    )
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settlement_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    txn_type: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    marketplace: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fulfillment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    product_sales: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    product_sales_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    shipping_credits: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    promotional_rebates: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    marketplace_withheld_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    selling_fees: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    fba_fees: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    other_transaction_fees: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    other: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False, server_default="1")
    fx_source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="native")
    total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="seed")
    row_key: Mapped[str] = mapped_column(String(64), nullable=False)


class AmzProduct(AmzTimestampMixin, Base):
    """A 自己的 SKU 档案(与 K 零交集)。product_line 决定成本、季节相位、员工规则的分组。"""

    __tablename__ = "amz_products"

    store_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("amz_stores.store_code", name="fk_amz_products_store", ondelete="CASCADE"), primary_key=True
    )
    sku: Mapped[str] = mapped_column(String(128), primary_key=True)
    asin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    parent_asin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    product_line: Mapped[str] = mapped_column(String(32), nullable=False, server_default="other")
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    cost_factory: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    cost_freight: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    cost_currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="CNY")
    lifecycle_phase: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    season_phase: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", json_type(), nullable=False, default=dict)


class AmzSuggestion(AmzTimestampMixin, Base):
    """员工发来的一条消息 = 一条建议。影子期只记录决定,不碰亚马逊。dedupe_key 让每日重跑不重复发。"""

    __tablename__ = "amz_suggestions"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_amz_suggestions_dedupe_key"),
        Index("ix_amz_suggestions_store_status", "store_code", "status"),
        Index("ix_amz_suggestions_employee_status", "employee", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    employee: Mapped[str] = mapped_column(String(4), nullable=False)
    store_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("amz_stores.store_code", name="fk_amz_suggestions_store", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False, server_default="info")
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    prediction: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    evidence_json: Mapped[dict[str, Any]] = mapped_column("evidence", json_type(), nullable=False, default=dict)
    level: Mapped[str] = mapped_column(String(4), nullable=False, server_default="L0")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AmzWorkLog(Base):
    """员工工作日志 = 硬记忆(建议 / 决定 / 执行 / 老板口述),聊天时按问题检索。无 org_id 列。"""

    __tablename__ = "amz_work_log"
    __table_args__ = (
        Index("ix_amz_work_log_employee_time", "employee", "occurred_at"),
        Index("ix_amz_work_log_store_subject", "store_code", "subject"),
        Index("ix_amz_work_log_suggestion", "suggestion_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    employee: Mapped[str] = mapped_column(String(4), nullable=False)
    store_code: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("amz_stores.store_code", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False, server_default="", default="")
    asin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False, server_default="", default="")
    detail_json: Mapped[dict[str, Any]] = mapped_column("detail", json_type(), nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="rule", default="rule")
    suggestion_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AmzSalesDaily(AmzTimestampMixin, Base):
    """销售与流量业务报表,按天;child_asin='' 的那行是店铺当天合计。来源 SP-API GET_SALES_AND_TRAFFIC_REPORT。"""

    __tablename__ = "amz_sales_daily"
    __table_args__ = (
        UniqueConstraint("store_code", "report_date", "child_asin", name="uq_amz_sales_daily_store_date_asin"),
        Index("ix_amz_sales_daily_store_date", "store_code", "report_date"),
        Index("ix_amz_sales_daily_asin", "child_asin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_code: Mapped[str] = mapped_column(String(16), ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    parent_asin: Mapped[str] = mapped_column(String(16), nullable=False, server_default="", default="")
    child_asin: Mapped[str] = mapped_column(String(16), nullable=False, server_default="", default="")
    units_ordered: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    ordered_product_sales: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0", default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_order_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    units_refunded: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    sessions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    page_views: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    buy_box_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    unit_session_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column("raw", json_type(), nullable=False, default=dict)


class AmzSqp(AmzTimestampMixin, Base):
    """Brand Analytics 搜索词表现(SQP),按周 × ASIN × 搜索词。份额 = 我们 / 全市场。"""

    __tablename__ = "amz_sqp"
    __table_args__ = (
        UniqueConstraint("store_code", "period_start", "asin", "search_query", name="uq_amz_sqp_store_period_asin_query"),
        Index("ix_amz_sqp_store_period", "store_code", "period_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_code: Mapped[str] = mapped_column(String(16), ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False)
    period_type: Mapped[str] = mapped_column(String(8), nullable=False, server_default="WEEK", default="WEEK")
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    asin: Mapped[str] = mapped_column(String(16), nullable=False)
    search_query: Mapped[str] = mapped_column(Text, nullable=False)
    query_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    query_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impressions_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    impressions_asin: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    impressions_share_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    clicks_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    clicks_asin: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    clicks_share_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    cart_adds_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    cart_adds_asin: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    cart_adds_share_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    purchases_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    purchases_asin: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    purchases_share_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column("raw", json_type(), nullable=False, default=dict)


class AmzReportRun(Base):
    """每次向亚马逊要报表的台账:要了什么、多久、拿回多少行、失败原因。"""

    __tablename__ = "amz_report_runs"
    __table_args__ = (Index("ix_amz_report_runs_store_type_time", "store_code", "report_type", "requested_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_code: Mapped[str] = mapped_column(String(16), ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False)
    report_type: Mapped[str] = mapped_column(String(80), nullable=False)
    report_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params_json: Mapped[dict[str, Any]] = mapped_column("params", json_type(), nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="requested", default="requested")
    rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AmzFactSheet(Base):
    """产品事实表:按 (产品线, 店, SKU) 一份,手填;sufficiency 是最近一次「够不够」判定。无 org_id 列。"""

    __tablename__ = "amz_fact_sheets"
    __table_args__ = (UniqueConstraint("scope_key", name="uq_amz_fact_sheets_scope"), Index("ix_amz_fact_sheets_line", "product_line"))

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False)
    product_line: Mapped[str] = mapped_column(String(32), nullable=False)
    store_code: Mapped[str | None] = mapped_column(String(16), ForeignKey("amz_stores.store_code", ondelete="SET NULL"), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    facts_json: Mapped[dict[str, Any]] = mapped_column("facts", json_type(), nullable=False, default=dict)
    sufficiency_json: Mapped[dict[str, Any]] = mapped_column("sufficiency", json_type(), nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft", default="draft")
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AmzImageBrief(AmzTimestampMixin, Base):
    """图片 brief:带证据(在哪个词上同屏输给谁)、必须出现 / 禁止出现(来自事实表)、轮数上限、上线后回看。无 org_id 列。"""

    __tablename__ = "amz_image_briefs"
    __table_args__ = (Index("ix_amz_image_briefs_store_status", "store_code", "status"), Index("ix_amz_image_briefs_suggestion", "source_suggestion_id"))

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    store_code: Mapped[str] = mapped_column(String(16), ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    asin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    product_line: Mapped[str] = mapped_column(String(32), nullable=False, server_default="other", default="other")
    position: Mapped[str] = mapped_column(String(16), nullable=False, server_default="main", default="main")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued", default="queued")
    brief_md: Mapped[str] = mapped_column(Text, nullable=False, server_default="", default="")
    evidence_json: Mapped[dict[str, Any]] = mapped_column("evidence", json_type(), nullable=False, default=dict)
    must_have_json: Mapped[list[Any]] = mapped_column("must_have", json_type(), nullable=False, default=list)
    forbidden_json: Mapped[list[Any]] = mapped_column("forbidden", json_type(), nullable=False, default=list)
    rounds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    max_rounds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="4", default=4)
    source_suggestion_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    fact_sheet_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    chosen_asset_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    live_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    baseline_json: Mapped[dict[str, Any]] = mapped_column("baseline", json_type(), nullable=False, default=dict)
    lookback_json: Mapped[dict[str, Any]] = mapped_column("lookback", json_type(), nullable=False, default=dict)


class AmzImageAsset(AmzTimestampMixin, Base):
    """一张图:参考图(product_photo / current_main / sibling_main / competitor_thumb)或交稿(submission),带四道门结果。"""

    __tablename__ = "amz_image_assets"
    __table_args__ = (Index("ix_amz_image_assets_brief_kind", "brief_id", "kind"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    brief_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("amz_image_briefs.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    dhash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_via: Mapped[str] = mapped_column(String(16), nullable=False, server_default="upload", default="upload")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="available", default="available")
    review_json: Mapped[dict[str, Any]] = mapped_column("review", json_type(), nullable=False, default=dict)
    decided_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AmzOutcome(Base):
    """一条建议在 14 / 28 天后对不对(live = 真建议;backtest = 规则放回过去跑)。无 org_id 列。"""

    __tablename__ = "amz_outcomes"
    __table_args__ = (
        UniqueConstraint("store_code", "action_type", "subject", "as_of", "horizon_days", "source", name="uq_amz_outcomes_key"),
        Index("ix_amz_outcomes_store_action", "store_code", "action_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_code: Mapped[str] = mapped_column(String(16), ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="live", default="live")
    verdict: Mapped[str] = mapped_column(String(8), nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column("metrics", json_type(), nullable=False, default=dict)
    suggestion_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AmzExperience(Base):
    """经验条目(precision / rejection / image)与参数漂移(param)。一句人话 + 证据 + 样本数。"""

    __tablename__ = "amz_experience"
    __table_args__ = (UniqueConstraint("entry_key", name="uq_amz_experience_key"), Index("ix_amz_experience_store_action", "store_code", "action_type"))

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    entry_key: Mapped[str] = mapped_column(String(200), nullable=False)
    scope: Mapped[str] = mapped_column(String(8), nullable=False, server_default="store", default="store")
    store_code: Mapped[str | None] = mapped_column(String(16), ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    employee: Mapped[str | None] = mapped_column(String(4), nullable=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column("evidence", json_type(), nullable=False, default=dict)
    samples: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    value: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active", default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AmzLaunch(AmzTimestampMixin, Base):
    """推新六步状态机:损益表门 → 看战场 → 建 listing → 上架前门 → 蜜月 45 天 → 第 45 天判 → 复盘。无 org_id 列。"""

    __tablename__ = "amz_launches"
    __table_args__ = (Index("ix_amz_launches_store_stage", "store_code", "stage"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    store_code: Mapped[str] = mapped_column(String(16), ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False)
    product_line: Mapped[str] = mapped_column(String(32), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    asin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pnl", default="pnl")
    inputs_json: Mapped[dict[str, Any]] = mapped_column("inputs", json_type(), nullable=False, default=dict)
    pnl_json: Mapped[dict[str, Any]] = mapped_column("pnl", json_type(), nullable=False, default=dict)
    battlefield_json: Mapped[dict[str, Any]] = mapped_column("battlefield", json_type(), nullable=False, default=dict)
    checklist_json: Mapped[dict[str, Any]] = mapped_column("checklist", json_type(), nullable=False, default=dict)
    honeymoon_json: Mapped[dict[str, Any]] = mapped_column("honeymoon", json_type(), nullable=False, default=dict)
    verdict_json: Mapped[dict[str, Any]] = mapped_column("verdict", json_type(), nullable=False, default=dict)
    retro_json: Mapped[dict[str, Any]] = mapped_column("retro", json_type(), nullable=False, default=dict)
    live_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AmzReview(AmzTimestampMixin, Base):
    """贴进来的评论(自家 / 对手)+ 归簇结果。亚马逊没有评论正文 API。"""

    __tablename__ = "amz_reviews"
    __table_args__ = (UniqueConstraint("product_line", "whose", "asin", "text_sha256", name="uq_amz_reviews_text"), Index("ix_amz_reviews_line_whose", "product_line", "whose"))

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    launch_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("amz_launches.id", ondelete="CASCADE"), nullable=True)
    store_code: Mapped[str | None] = mapped_column(String(16), ForeignKey("amz_stores.store_code", ondelete="SET NULL"), nullable=True)
    product_line: Mapped[str] = mapped_column(String(32), nullable=False)
    asin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    whose: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ours", default="ours")
    stars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    family: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cluster: Mapped[str | None] = mapped_column(String(120), nullable=True)
    clustered_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    posted_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AmzCompetitor(Base):
    """盯的 ASIN:对手或自家。站点 + ASIN 唯一。无 org_id 列。"""

    __tablename__ = "amz_competitors"
    __table_args__ = (UniqueConstraint("marketplace", "asin", name="uq_amz_competitors_market_asin"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    marketplace: Mapped[str] = mapped_column(String(4), nullable=False)
    asin: Mapped[str] = mapped_column(String(16), nullable=False)
    product_line: Mapped[str] = mapped_column(String(32), nullable=False, server_default="other", default="other")
    whose: Mapped[str] = mapped_column(String(16), nullable=False, server_default="competitor", default="competitor")
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="manual", default="manual")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AmzCompetitorSnapshot(Base):
    """每天一张 Keepa 快照。"""

    __tablename__ = "amz_competitor_snapshots"
    __table_args__ = (UniqueConstraint("marketplace", "asin", "snap_date", name="uq_amz_competitor_snap_day"), Index("ix_amz_competitor_snapshots_asin_date", "marketplace", "asin", "snap_date"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    marketplace: Mapped[str] = mapped_column(String(4), nullable=False)
    asin: Mapped[str] = mapped_column(String(16), nullable=False)
    snap_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    in_stock: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    reviews: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bsr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_sold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coupon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column("raw", json_type(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AmzBaTopClick(Base):
    """品牌分析搜索词报表:我们核心词的点击前三(每周)。竞品名单从这里派生,不用人填。"""

    __tablename__ = "amz_ba_top_clicks"
    __table_args__ = (UniqueConstraint("marketplace", "week_start", "search_term", "click_rank", name="uq_amz_ba_top_clicks_week_term_rank"), Index("ix_amz_ba_top_clicks_asin", "marketplace", "asin", "week_start"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    marketplace: Mapped[str] = mapped_column(String(4), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    search_term: Mapped[str] = mapped_column(Text, nullable=False)
    product_line: Mapped[str] = mapped_column(String(32), nullable=False)
    search_frequency_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    click_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    asin: Mapped[str] = mapped_column(String(16), nullable=False)
    item_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    click_share: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    conversion_share: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AmzInventoryDaily(Base):
    """FBA 库存每天一张(SP-API FBA Inventory summaries)。库存天数 / 断货规则和跨店需求合成的底数。"""

    __tablename__ = "amz_inventory_daily"
    __table_args__ = (UniqueConstraint("store_code", "snap_date", "sku", name="uq_amz_inventory_daily_store_day_sku"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_code: Mapped[str] = mapped_column(String(16), ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False)
    snap_date: Mapped[date] = mapped_column(Date, nullable=False)
    sku: Mapped[str] = mapped_column(String(128), nullable=False)
    asin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fnsku: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fulfillable: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    inbound: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    unfulfillable: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    raw_json: Mapped[dict[str, Any]] = mapped_column("raw", json_type(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AmzListingSnapshot(Base):
    """自家 listing 每天一张(Listings Items API):标题 / 五点 / 描述 / 价格。内容变了 = 有人改了 listing,记进殷笑笑的工作日志。"""

    __tablename__ = "amz_listing_snapshots"
    __table_args__ = (UniqueConstraint("store_code", "sku", "snap_date", name="uq_amz_listing_snap_day"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_code: Mapped[str] = mapped_column(String(16), ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False)
    sku: Mapped[str] = mapped_column(String(128), nullable=False)
    snap_date: Mapped[date] = mapped_column(Date, nullable=False)
    asin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    bullets_json: Mapped[list[str]] = mapped_column("bullets", json_type(), nullable=False, default=list)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AmzSolicitation(Base):
    """请求留评(亚马逊官方 Solicitations「Request a Review」)。一单一行;影子期只记 would_request,总闸开了才真发。"""

    __tablename__ = "amz_solicitations"
    __table_args__ = (UniqueConstraint("store_code", "order_id", name="uq_amz_solicitations_store_order"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_code: Mapped[str] = mapped_column(String(16), ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False)
    order_id: Mapped[str] = mapped_column(String(32), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ordered_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AmzActionLedger(Base):
    """执行台账:一条放行(或 L2 倒计时 / L3 自动)的建议 = 一行。改前 / 改后 / 原因 / 预测 / 谁批 / 护栏 / 回读 / 7-14-28 天回看。"""

    __tablename__ = "amz_actions_ledger"
    __table_args__ = (UniqueConstraint("suggestion_id", name="uq_amz_actions_ledger_suggestion"), Index("ix_amz_actions_ledger_store_status", "store_code", "status"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    suggestion_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    store_code: Mapped[str] = mapped_column(String(16), ForeignKey("amz_stores.store_code", ondelete="CASCADE"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    level: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    op_json: Mapped[dict[str, Any]] = mapped_column("op", json_type(), nullable=False, default=dict)
    before_json: Mapped[dict[str, Any]] = mapped_column("before", json_type(), nullable=False, default=dict)
    after_json: Mapped[dict[str, Any]] = mapped_column("after", json_type(), nullable=False, default=dict)
    why: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prediction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approved_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    guard_json: Mapped[dict[str, Any]] = mapped_column("guard", json_type(), nullable=False, default=dict)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    countdown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    readback_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    lookback_json: Mapped[dict[str, Any]] = mapped_column("lookback", json_type(), nullable=False, default=dict)
    outcome: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AmzLadder(Base):
    """(动作 × 店铺) → 级别。升要人批、降自动;history 记每次变化。"""

    __tablename__ = "amz_ladder"

    store_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("amz_stores.store_code", name="fk_amz_ladder_store", ondelete="CASCADE"), primary_key=True
    )
    action_type: Mapped[str] = mapped_column(String(48), primary_key=True)
    level: Mapped[str] = mapped_column(String(4), nullable=False, server_default="L0")
    max_level: Mapped[str] = mapped_column(String(4), nullable=False, server_default="L1")
    history_json: Mapped[list[Any]] = mapped_column("history", json_type(), nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AmzGuardrail(Base):
    """每店五道护栏 + 总闸。任何级别都不动;数值在影子期结束按真实水位定。"""

    __tablename__ = "amz_guardrails"

    store_code: Mapped[str] = mapped_column(
        String(16), ForeignKey("amz_stores.store_code", name="fk_amz_guardrails_store", ondelete="CASCADE"), primary_key=True
    )
    daily_budget_cap: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    bid_max_change_pct: Mapped[int] = mapped_column(Integer, nullable=False, server_default="25")
    budget_max_change_pct: Mapped[int] = mapped_column(Integer, nullable=False, server_default="20")
    actions_per_day: Mapped[int] = mapped_column(Integer, nullable=False, server_default="20")
    cpc_max: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    price_floor: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    breaker_ratio: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, server_default="1.3")
    kill_switch: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    kill_switch_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kill_switch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


__all__ = [
    "AmzAdSearchTerm",
    "AmzFxRate",
    "AmzGuardrail",
    "AmzJob",
    "AmzLadder",
    "AmzProduct",
    "AmzSeedImport",
    "AmzStore",
    "AmzStoreGrant",
    "AmzSuggestion",
    "AmzTransaction",
    "AmzWorkLog",
    "AmzSalesDaily",
    "AmzSqp",
    "AmzReportRun",
    "AmzFactSheet",
    "AmzImageBrief",
    "AmzImageAsset",
    "AmzOutcome",
    "AmzExperience",
    "AmzLaunch",
    "AmzReview",
    "AmzCompetitor",
    "AmzCompetitorSnapshot",
]
