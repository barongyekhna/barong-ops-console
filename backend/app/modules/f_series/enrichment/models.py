"""SQLAlchemy models for the F category enrichment table family.

F 不复刻类目树：谷歌树共享 K 的 ``k_category_google``（裸 SQL 访问），这里只有
F 自己的状态层——富化运行、每类目收割到的关键词、以及 1688 货源候选池。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ....db.base import Base
from ....models.base_mixins import json_type


class FUUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class FTimestampMixin:
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


class FEnrichmentRun(FUUIDPrimaryKeyMixin, FTimestampMixin, Base):
    """一次「选类目→爬关键词」运行的台账（进度轮询 + 收尸都靠它）。"""

    __tablename__ = "f_enrichment_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'queued', 'running', 'succeeded', 'failed', "
            "'quota_exhausted', 'cancelled'"
            ")",
            name=conv("ck_f_runs_valid_status"),
        ),
        CheckConstraint(
            "mode IN ('full', 'keywords_only', 'sourcing_only')",
            name=conv("ck_f_runs_valid_mode"),
        ),
        Index("ix_f_runs_status", "status"),
        Index("ix_f_runs_created", "created_at"),
    )

    # 用户勾选的节点快照：[{id, name, full_path}, ...]（展开后的目标见 stats）
    selection_json: Mapped[Any] = mapped_column(json_type(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default="queued",
    )
    # full = 爬词+1688找货（默认一键全链）；历史行是纯爬词。
    mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="keywords_only",
    )
    categories_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    categories_done: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    keywords_found: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    serper_calls: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    candidates_found: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    alibaba_calls: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    requested_by_username: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FCategoryKeyword(FUUIDPrimaryKeyMixin, FTimestampMixin, Base):
    """按类目落库的收割关键词（去重：同类目同词只存一次，跨运行累积）。"""

    __tablename__ = "f_category_keywords"
    __table_args__ = (
        CheckConstraint(
            "keyword_type IN ('related', 'people_also_ask', 'organic_title')",
            name=conv("ck_f_keywords_valid_type"),
        ),
        CheckConstraint(
            "status IN ('candidate', 'approved', 'rejected')",
            name=conv("ck_f_keywords_valid_status"),
        ),
        UniqueConstraint(
            "category_id",
            "keyword_text",
            name="uq_f_keywords_category_keyword",
        ),
        Index("ix_f_keywords_category_status", "category_id", "status"),
        Index("ix_f_keywords_run", "run_id"),
        Index("ix_f_keywords_created", "created_at"),
    )

    run_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("f_enrichment_runs.id", name="fk_f_keywords_run_id_runs"),
        nullable=True,
    )
    # 谷歌树节点（k_category_google.id）；路径冗余存一份便于展示/检索。
    category_id: Mapped[str] = mapped_column(String(32), nullable=False)
    category_path: Mapped[str] = mapped_column(Text, nullable=False)
    keyword_text: Mapped[str] = mapped_column(String(512), nullable=False)
    keyword_type: Mapped[str] = mapped_column(String(30), nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="serper_search",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="candidate",
    )
    reviewed_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FCategoryProfile(FUUIDPrimaryKeyMixin, FTimestampMixin, Base):
    """类目产品画像缓存：DeepSeek 生成一次，永久复用。"""

    __tablename__ = "f_category_profiles"
    __table_args__ = (
        UniqueConstraint("category_id", name="uq_f_profiles_category"),
        Index("ix_f_profiles_category", "category_id"),
    )

    category_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # [{"en": "...", "zh": "...", "note_zh": "..."}]
    products_json: Mapped[Any] = mapped_column(json_type(), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="deepseek",
    )


class FProductMarketRef(FUUIDPrimaryKeyMixin, FTimestampMixin, Base):
    """市场参考页：图搜接力拿种子图时顺手收割的图片来源网页。

    用途（2026-07-14 用户需求）：看竞品怎么定价、怎么配变体（多个装等），
    展示在候选池每个画像产品分组上方。每产品每轮最多存 3 条，
    (category, product, page_url) 去重。"""

    __tablename__ = "f_product_market_refs"
    __table_args__ = (
        Index("ix_f_market_refs_group", "category_id", "profile_product_zh"),
    )

    category_id: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_product_zh: Mapped[str] = mapped_column(String(200), nullable=False)
    profile_product_en: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    page_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # independent（独立站，用户硬规则：优先且至少一条）/ platform / content
    site_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    run_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class FCategoryCandidate(FUUIDPrimaryKeyMixin, FTimestampMixin, Base):
    """类目候选池：1688 货源候选（当前人工贴链接，API 过审后自动填充）。

    红线只标记不毙掉：``red_flags_json`` 记录命中原因，``automation_blocked``
    表示不准走任何自动链路——但用户人工放行（approve）后仍可手动进 K。
    """

    __tablename__ = "f_category_candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'pending_review', 'approved', 'rejected', 'imported_to_k'"
            ")",
            name=conv("ck_f_candidates_valid_status"),
        ),
        Index("ix_f_candidates_category_status", "category_id", "status"),
        Index("ix_f_candidates_run", "run_id"),
        Index("ix_f_candidates_created", "created_at"),
        Index(
            "ix_f_candidates_category_product",
            "category_id",
            "profile_product_zh",
        ),
    )

    run_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("f_enrichment_runs.id", name="fk_f_candidates_run_id_runs"),
        nullable=True,
    )
    category_id: Mapped[str] = mapped_column(String(32), nullable=False)
    category_path: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # manual = 人工贴 1688 链接（过渡期）；alibaba1688 = API 自动填充（下一刀）
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="manual",
    )
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    price_cny: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    moq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 供应商报重（自由文本，先记录来源；W 系列运费规则表落地后转结构化）
    weight_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    red_flags_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    automation_blocked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default="pending_review",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 对比进阶档：来源画像产品（分组键）+ 推荐分 + 组内 top3 名次
    profile_product_zh: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    profile_product_en: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    recommended_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    k_product_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
