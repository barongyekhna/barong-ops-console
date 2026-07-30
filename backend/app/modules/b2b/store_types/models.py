"""店型 = B2B 的主键,不是产品类目。

2026-07-28 用户提出的问题催生了这一层:"产品类目多了以后我不知道你这个怎么
hold 得住,一个产品找五六种买家,十个产品就得有五六十个买家类型,我回复都不
知道该怎么回复了"。

答案是把乘法倒过来:**零售店的种类远少于产品的种类**。一家礼品店同时买捏捏球
和家居小件,他是一个买家买了两样东西,不是两个买家。所以:

- 产品从 10 个涨到 300 个,店型还是四五种;变的是**每种店型的图册变厚**,
  同一个买家客单价从 $600 涨到 $2000。
- 挖客户、发信、出图册,全部以店型为主键;类目只是"这个店型能拿到哪些货"
  的实现细节。
- **一次只允许一种店型在外面跑**(`B2B_MAX_ACTIVE_STORE_TYPES`,默认 1)。
  用户一个人,同时在跟的对话必须恒定,否则类目一多他本人就是瓶颈。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ....db.base import Base

OUTREACH_IDLE = "idle"
OUTREACH_ACTIVE = "active"
OUTREACH_PAUSED = "paused"
OUTREACH_RETIRED = "retired"
OUTREACH_STATUSES = (
    OUTREACH_IDLE,
    OUTREACH_ACTIVE,
    OUTREACH_PAUSED,
    OUTREACH_RETIRED,
)


class B2BStoreType(Base):
    """一种零售店档口(礼品店/户外店/五金店…)。"""

    __tablename__ = "b2b_store_types"
    __table_args__ = (
        UniqueConstraint("key", name="uq_b2b_store_types_key"),
        CheckConstraint(
            "outreach_status IN ('idle', 'active', 'paused', 'retired')",
            name=conv("ck_b2b_store_types_outreach_status"),
        ),
        Index("ix_b2b_store_types_outreach_status", "outreach_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # 和 b2b_prospect_queries.store_type 是同一套 key。
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    outreach_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=OUTREACH_IDLE,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
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


class B2BStoreTypeCategory(Base):
    """店型 ↔ 类目前缀。多对多:一个店型吃多个类目,一个类目可进多个店型。

    存的是**前缀**不是全路径——`["Toys & Games"]` 会吃掉它底下所有叶子类目,
    新上架的品自动落进对应店型的图册,不用每次手动挂。
    """

    __tablename__ = "b2b_store_type_categories"
    __table_args__ = (
        UniqueConstraint(
            "store_type_id",
            "category_key",
            name="uq_b2b_store_type_categories_pair",
        ),
        Index("ix_b2b_store_type_categories_store", "store_type_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    store_type_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("b2b_store_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 前缀本体(JSON 列表)。category_key 是它的规范化字符串形式,只为唯一约束
    # 服务——Postgres 的 json 类型没有相等运算符,不能直接进 UNIQUE。
    category_prefix: Mapped[list] = mapped_column(JSON, nullable=False)
    category_key: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
