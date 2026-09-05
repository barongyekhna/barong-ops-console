"""SM 系列表。全部按 workspace_key / business_context / scope_mode 分区，
与 K/GEO 同一套 ``apply_scope_filters``；读端点漏传 scope = 跨组织泄漏
（geo-seo-workspace-leak-class），所以模型层就把三列钉死。

``sm_posts`` 多带四列 ``wp_post_id / wp_status / published_url / published_at``：
内容台 ``dto.to_article`` 通读这些属性，社媒帖没有 WordPress，这四列恒空，
只是让第三源头「加一行」成立。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from ...db.base import Base
from ..k_series.product_knowledge.constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_SCOPE_MODE,
    DEFAULT_WORKSPACE_KEY,
)


def json_type() -> JSON:
    """与 ``models.base_mixins.json_type`` 同义。本地定义是为了避开循环导入：
    ``backend.app.models`` 的包初始化会导入本模块，本模块再去导入那个包就转圈了。"""
    return JSON().with_variant(JSONB(), "postgresql")


class SmUUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class SmTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SmScopeMixin:
    """租户三元组；与 K 一致，``apply_scope_filters`` 原样可用。"""

    workspace_key: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default=DEFAULT_WORKSPACE_KEY
    )
    business_context: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default=DEFAULT_BUSINESS_CONTEXT
    )
    scope_mode: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DEFAULT_SCOPE_MODE
    )


class SmChannel(SmUUIDPrimaryKeyMixin, SmScopeMixin, SmTimestampMixin, Base):
    """一个平台账号。mock 期 mode 只有 manual；created_at 是账号阶段的起点。"""

    __tablename__ = "sm_channels"
    __table_args__ = (
        UniqueConstraint("workspace_key", "platform", name="uq_sm_channels_ws_platform"),
    )

    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="manual")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    key_alias: Mapped[str | None] = mapped_column(String(128), nullable=True)
    profile_version: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SmCalendarSlot(SmUUIDPrimaryKeyMixin, SmScopeMixin, SmTimestampMixin, Base):
    """排期器产出的一格：哪天、哪个平台、哪根支柱、哪个源头、配哪张图。"""

    __tablename__ = "sm_calendar_slots"
    __table_args__ = (
        UniqueConstraint(
            "workspace_key", "day", "platform", "slot_index", name="uq_sm_slots_ws_day_platform_idx"
        ),
        Index("ix_sm_slots_ws_day", "workspace_key", "day"),
        Index("ix_sm_slots_status", "status"),
    )

    day: Mapped[date] = mapped_column(Date, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    window_pt: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pillar: Mapped[str] = mapped_column(String(4), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="none")
    source_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    seed_product_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    # planned → writing → filled → posted；blocked（没源头）；swapped（缺图临期换柱）
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="planned")
    swap_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    media_plan_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    planner_version: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_run_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class SmPost(SmUUIDPrimaryKeyMixin, SmScopeMixin, SmTimestampMixin, Base):
    """一条帖子。内容台通读 ``title / body_json / seo_json / *_json / review_status``。"""

    __tablename__ = "sm_posts"
    __table_args__ = (
        Index("ix_sm_posts_ws_review", "workspace_key", "review_status"),
        Index("ix_sm_posts_slot", "slot_id"),
        Index("ix_sm_posts_platform", "platform"),
    )

    slot_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("sm_calendar_slots.id", name="fk_sm_posts_slot_id_slots", ondelete="SET NULL"),
        nullable=True,
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    post_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    pillar: Mapped[str] = mapped_column(String(4), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    seed_product_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)

    title: Mapped[str] = mapped_column(String(512), nullable=False, server_default="")
    first_line: Mapped[str | None] = mapped_column(String(512), nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    alt_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashtags_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    board: Mapped[str | None] = mapped_column(String(255), nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    media_refs_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    keyword_primary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    keywords_secondary_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    cta: Mapped[str | None] = mapped_column(String(255), nullable=True)
    facts_used_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)

    # 内容台通用形状
    body_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    seo_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    brand_audit_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    analysis_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    revision_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)

    review_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    generation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft"
    )
    publish_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    permalink: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 内容台 to_article 通读；社媒无 WordPress，恒空。
    wp_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wp_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    published_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    skill_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SmMediaUsage(SmUUIDPrimaryKeyMixin, SmScopeMixin, Base):
    """同一张图片文件在同一平台只用一次（新鲜度）。"""

    __tablename__ = "sm_media_usage"
    __table_args__ = (
        UniqueConstraint(
            "workspace_key", "asset_id", "platform", name="uq_sm_media_usage_ws_asset_platform"
        ),
    )

    asset_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    post_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SmImageRequest(SmUUIDPrimaryKeyMixin, SmScopeMixin, SmTimestampMixin, Base):
    """缺口单。lane 决定谁来填：layout 代码当场填；mcp 进 K 简报社媒位号；
    photo 只登记，等吉林的人拍。"""

    __tablename__ = "sm_image_requests"
    __table_args__ = (
        Index("ix_sm_image_requests_ws_status", "workspace_key", "status"),
        Index("ix_sm_image_requests_product", "seed_product_id"),
    )

    slot_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    seed_product_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    pillar: Mapped[str] = mapped_column(String(4), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    ratio: Mapped[str] = mapped_column(String(8), nullable=False, server_default="2:3")
    lane: Mapped[str] = mapped_column(String(16), nullable=False)
    k_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_day: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    filled_asset_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    brief_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SmRejection(SmUUIDPrimaryKeyMixin, SmScopeMixin, Base):
    """驳回记录：被驳回的图永远不再推给同平台同支柱。"""

    __tablename__ = "sm_rejections"
    __table_args__ = (Index("ix_sm_rejections_ws_platform_pillar", "workspace_key", "platform", "pillar"),)

    post_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    object: Mapped[str] = mapped_column(String(16), nullable=False)  # image | copy
    asset_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    pillar: Mapped[str] = mapped_column(String(4), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    replacement_asset_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SmGenerationJob(SmUUIDPrimaryKeyMixin, SmScopeMixin, SmTimestampMixin, Base):
    """写手 / 重写 / 版式任务队列，sm-worker 用 FOR UPDATE SKIP LOCKED 领。"""

    __tablename__ = "sm_generation_jobs"
    __table_args__ = (Index("ix_sm_jobs_status_created", "status", "created_at"),)

    slot_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    post_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    job_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    requested_by_username: Mapped[str | None] = mapped_column(String(150), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "SmCalendarSlot",
    "SmChannel",
    "SmGenerationJob",
    "SmImageRequest",
    "SmMediaUsage",
    "SmPost",
    "SmRejection",
    "SmScopeMixin",
]
