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
]
