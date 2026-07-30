"""SQLAlchemy models for B2B customer prospecting.

设计要点(2026-07-27 与用户敲定):
- **店铺类型和查询词是数据不是代码**。以后上了新品类(园艺灯…),在界面上
  加一行查询模板即可,不改代码不发版。
- **城市不按"前 N 大"挑**。用户判断:大城市精品店每周收几十封开发信,小镇
  店铺几乎没人找过——小城市反而机会大。所以城市表按人口存全量,跑批按人口
  降序但全都要跑。
- **跑批记录独立成表**,支持断点续跑、不重复烧额度。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ....db.base import Base

PROSPECT_STATUS_NEW = "new"
PROSPECT_STATUS_APPROVED = "approved"
PROSPECT_STATUS_REJECTED = "rejected"
PROSPECT_STATUS_CONTACTED = "contacted"
PROSPECT_STATUS_REPLIED = "replied"
PROSPECT_STATUS_CUSTOMER = "customer"
PROSPECT_STATUSES = (
    PROSPECT_STATUS_NEW,
    PROSPECT_STATUS_APPROVED,
    PROSPECT_STATUS_REJECTED,
    PROSPECT_STATUS_CONTACTED,
    PROSPECT_STATUS_REPLIED,
    PROSPECT_STATUS_CUSTOMER,
)


class B2BProspectQuery(Base):
    """一条查询模板 = 店铺类型 × 国家 × 语言 × 搜索词。"""

    __tablename__ = "b2b_prospect_queries"
    __table_args__ = (
        UniqueConstraint(
            "store_type",
            "country",
            "query_template",
            name="uq_b2b_prospect_queries_combo",
        ),
        CheckConstraint(
            "country IN ('US', 'CA', 'MX')",
            name=conv("ck_b2b_prospect_queries_country"),
        ),
        Index("ix_b2b_prospect_queries_active", "active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    store_type: Mapped[str] = mapped_column(String(64), nullable=False)
    store_type_label: Mapped[str] = mapped_column(String(128), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    # 必须含 {city} 占位符,跑批时替换成城市名。
    query_template: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=true(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class B2BTargetCity(Base):
    """目标城市。人口只用来排序,不用来筛掉小城市。"""

    __tablename__ = "b2b_target_cities"
    __table_args__ = (
        UniqueConstraint(
            "country",
            "region",
            "city",
            name="uq_b2b_target_cities_place",
        ),
        CheckConstraint(
            "country IN ('US', 'CA', 'MX')",
            name=conv("ck_b2b_target_cities_country"),
        ),
        Index("ix_b2b_target_cities_country_active", "country", "active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    city: Mapped[str] = mapped_column(String(128), nullable=False)
    population: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 越大越先跑;默认 0,用户可以手动置顶某些城市。
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=true(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class B2BProspectSweep(Base):
    """(查询模板 × 城市) 跑过没有。断点续跑靠它,重复跑靠它拦。"""

    __tablename__ = "b2b_prospect_sweeps"
    __table_args__ = (
        UniqueConstraint(
            "query_id",
            "city_id",
            name="uq_b2b_prospect_sweeps_pair",
        ),
        Index("ix_b2b_prospect_sweeps_ran_at", "ran_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    query_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    city_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    results_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    new_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class B2BProspect(Base):
    """一家候选零售店。去重键是网站域名(同一家店会被多个词重复抓到)。"""

    __tablename__ = "b2b_prospects"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_b2b_prospects_dedupe_key"),
        CheckConstraint(
            "status IN ('new', 'approved', 'rejected', 'contacted', "
            "'replied', 'customer')",
            name=conv("ck_b2b_prospects_status"),
        ),
        Index("ix_b2b_prospects_status", "status"),
        Index("ix_b2b_prospects_country_store_type", "country", "store_type"),
        Index("ix_b2b_prospects_screen_verdict", "screen_verdict"),
        CheckConstraint(
            "screen_verdict IS NULL OR screen_verdict IN ('fit', 'unfit', 'unsure')",
            name=conv("ck_b2b_prospects_screen_verdict"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # 有网站就用域名,没网站退化成"店名+城市"——保证总有去重键。
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)

    store_name: Mapped[str] = mapped_column(String(255), nullable=False)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    rating: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reviews_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    store_type: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    source_query: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 人工审核的两个关键依据:谷歌给的店铺类型,以及地图 ID(拼成链接点开
    # 就能看店面照片和官网——Serper 的接口本身不返回网站)。
    place_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    place_cid: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 自动筛选结果:机器读官网判断这家店值不值得发。用户只读 screen_reason
    # 那一句人话——"我没办法通过这点信息确定"(2026-07-28)催生的这一层。
    website_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    screen_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    screen_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    screen_signals_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    screened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # 开发信首句(AI 读官网时**顺手**写的,不额外花一次调用)。这句话决定
    # 对方觉得你是不是群发,是整封信里最值钱的一行。
    personal_line: Mapped[str | None] = mapped_column(String(500), nullable=True)

    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    email_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=PROSPECT_STATUS_NEW,
    )
    reject_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
