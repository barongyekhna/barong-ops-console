"""SEO 内容引擎的表。

和 GEO 同构(选题 → 内容 → 生成队列 → 发布队列),但**选题依据完全不同**:
GEO 的单位是"买家问句 + 谷歌类目簇",SEO 的单位是"关键词 / 店型 / 工艺话题"。
这也是为什么它不复用 ``geo_content_*``——共享的是能力(守卫、事实门禁、发布
拼装),不是选题口径。
"""

from __future__ import annotations

from datetime import datetime
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
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ....db.base import Base
from ....models.base_mixins import json_type
from .constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_SCOPE_MODE,
    DEFAULT_WORKSPACE_KEY,
)


class _Scope:
    workspace_key: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default=DEFAULT_WORKSPACE_KEY
    )
    business_context: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DEFAULT_BUSINESS_CONTEXT
    )
    scope_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=DEFAULT_SCOPE_MODE
    )


class _Stamp:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SeoTopic(_Scope, _Stamp, Base):
    """一个候选选题。雷达产出的、店型推出来的、手输的,都落这张表。

    最重要的两列不是搜索量,是 ``geo_reachable`` 和 ``fact_support_json``:
    - **GEO 够得到的,SEO 不碰**——同一个话题两边都写就是自我竞争。
    - **三源都无支撑的,写出来就是 AI 垃圾**——雷达在这里就标红,并说明缺什么,
      而不是等生成时才被事实门禁拦下。
    """

    __tablename__ = "seo_topics"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate', 'picked', 'rejected', 'written')",
            name=conv("ck_seo_topics_status"),
        ),
        CheckConstraint(
            "audience IN ('consumer', 'wholesale', 'brand')",
            name=conv("ck_seo_topics_audience"),
        ),
        CheckConstraint(
            "destination IN ('factory', 'posts')",
            name=conv("ck_seo_topics_destination"),
        ),
        Index("ix_seo_topics_status", "status"),
        Index("ix_seo_topics_audience", "audience"),
        Index("ix_seo_topics_norm", "normalized_keyword"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    # 去重键:小写、压空白、去问号。雷达反复跑不会堆重复行。
    normalized_keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    destination: Mapped[str] = mapped_column(String(16), nullable=False)

    # 谷歌类目——B 端店型和 C 端选题都靠它和产品/批发页对齐(内链的连接键)。
    google_category_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    store_type_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    craft_topic: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Keyword Planner 指标。拿不到就是 None——**没有搜索量不等于不该写**,
    # B 端采购词量小到测不出来,却是最值钱的话题。
    avg_monthly_searches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    competition_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cpc_high_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 可攻度:复用 GEO 阵地监测那套(守门人榜单占位=难打,论坛/视频占位=能打)。
    attackability: Mapped[int | None] = mapped_column(Integer, nullable=True)
    terrain: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # GEO 可达性去重门。True = 这题是 GEO 的地盘,SEO 不写。
    geo_reachable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    geo_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # {"supported": [...], "missing": [...], "sources": {...}}
    fact_support_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="candidate"
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    picked_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class SeoContentItem(_Scope, _Stamp, Base):
    """一篇 SEO 文章。字段与 GEO item 刻意保持同形,好共用发布拼装与守卫。"""

    __tablename__ = "seo_content_items"
    __table_args__ = (
        CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected')",
            name=conv("ck_seo_items_review_status"),
        ),
        CheckConstraint(
            "generation_status IN ('queued', 'running', 'generated', 'failed')",
            name=conv("ck_seo_items_generation_status"),
        ),
        CheckConstraint(
            "item_kind IN ('craft_story', 'material_explainer', 'testing', "
            "'buying_guide', 'wholesale_guide', 'brand_story')",
            name=conv("ck_seo_items_kind"),
        ),
        CheckConstraint(
            "destination IN ('factory', 'posts')",
            name=conv("ck_seo_items_destination"),
        ),
        Index("ix_seo_items_topic", "topic_id"),
        Index("ix_seo_items_review", "review_status"),
        Index("ix_seo_items_wp_post", "wp_post_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    topic_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("seo_topics.id", name=conv("fk_seo_items_topic_id")),
        nullable=False,
    )
    item_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    destination: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    seo_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    # 内链意图:这篇该链到哪些产品/指南/批发页。发布后由占位回填成真 URL。
    links_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)

    brand_audit_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    analysis_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    revision_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)

    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    generation_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="generated"
    )
    skill_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)

    wp_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 死规矩:published_url 非空 ≠ 线上可见。真实状态看这一列。
    wp_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    published_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SeoGenerationJob(_Scope, _Stamp, Base):
    """seo-worker 排的生成任务队列。"""

    __tablename__ = "seo_generation_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'success', 'failed')",
            name=conv("ck_seo_generation_jobs_status"),
        ),
        Index("ix_seo_generation_jobs_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    topic_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("seo_topics.id", name=conv("fk_seo_generation_jobs_topic_id")),
        nullable=False,
    )
    job_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="generate"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="queued"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    requested_by_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SeoPublishJob(_Scope, _Stamp, Base):
    """派给 n8n ``barongSEOpublish001`` 的发布单。串行,一次一单。"""

    __tablename__ = "seo_publish_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'dispatched', 'success', 'failed')",
            name=conv("ck_seo_publish_jobs_status"),
        ),
        UniqueConstraint("job_id", name=conv("uq_seo_publish_jobs_job_id")),
        Index("ix_seo_publish_jobs_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # 给 n8n 用的短 id 与一次性令牌:发布包端点靠 token 鉴权(与 P/GEO 同规)。
    job_id: Mapped[str] = mapped_column(String(64), nullable=False)
    token: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="wordpress"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="queued"
    )
    item_ids_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    payload_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    result_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SeoRadarRun(_Scope, _Stamp, Base):
    """一次雷达跑批。记下花了多少额度、产出多少候选、拒了多少、为什么。

    没有这张表,「雷达跑过没有 / 上次为什么什么都没出」只能靠猜。
    """

    __tablename__ = "seo_radar_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'success', 'failed')",
            name=conv("ck_seo_radar_runs_status"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="running"
    )
    seed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    planner_calls: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    candidate_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    geo_blocked_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    notes_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = [
    "SeoContentItem",
    "SeoGenerationJob",
    "SeoPublishJob",
    "SeoRadarRun",
    "SeoTopic",
]
