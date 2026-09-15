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


__all__ = [
    "AmzAdSearchTerm",
    "AmzFxRate",
    "AmzJob",
    "AmzSeedImport",
    "AmzStore",
    "AmzStoreGrant",
    "AmzTransaction",
]
