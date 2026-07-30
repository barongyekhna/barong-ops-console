"""SQLAlchemy models for the GEO content engine.

Three tables, all scope-partitioned (workspace_key/business_context/scope_mode) so
they reuse K's ``apply_scope_filters`` for tenant isolation:

- ``geo_content_clusters`` — a topic cluster aligned to a K category node.
- ``geo_content_items``   — the individual AI-citable guide pieces in a cluster.
- ``geo_generation_jobs`` — the standalone queue the geo-worker drains.

The content generator READS K product facts (``k_product_knowledge_products``) and
the K category tree, but GEO owns its own tables and worker (decoupled from K).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    UniqueConstraint,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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


class GeoUUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class GeoTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class GeoScopeMixin:
    """The tenant scope triple; matches K so ``apply_scope_filters`` works verbatim."""

    workspace_key: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default=DEFAULT_WORKSPACE_KEY
    )
    business_context: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default=DEFAULT_BUSINESS_CONTEXT
    )
    scope_mode: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DEFAULT_SCOPE_MODE
    )


class GeoContentCluster(
    GeoUUIDPrimaryKeyMixin, GeoScopeMixin, GeoTimestampMixin, Base
):
    """A topic cluster aligned to one K category node (the hub-and-spoke root)."""

    __tablename__ = "geo_content_clusters"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'draft', 'generating', 'ready', 'needs_review', 'approved', 'archived'"
            ")",
            name=conv("ck_geo_clusters_valid_status"),
        ),
        Index(
            "ix_geo_clusters_scope_category",
            "workspace_key",
            "business_context",
            "scope_mode",
            "google_category_id",
        ),
        Index("ix_geo_clusters_status", "status"),
        Index("ix_geo_clusters_created", "created_at"),
    )

    # The K Google-taxonomy node this cluster covers (k_category_google.id), plus a
    # redundant breadcrumb for display. Nullable so a product-seeded cluster can be
    # created before category resolution completes.
    google_category_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The buyer-facing topic phrase, e.g. "portable camping showers".
    topic: Mapped[str | None] = mapped_column(String(512), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="draft"
    )
    # The K product that seeded this cluster (the pilot/test vehicle for the run).
    seed_product_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    # Every K product this cluster covers. One cluster per category: products in the
    # same category share the topic (5 near-identical stress balls → one authoritative
    # article linking all of them, never 5 duplicate articles).
    product_ids_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    # Products attached since the last generation — drives the "有新产品" banner.
    # Approved content is never silently invalidated (operator decides to refresh).
    pending_product_ids_json: Mapped[Any | None] = mapped_column(
        json_type(), nullable=True
    )
    # Operator-picked real buyer questions (from topic sourcing) that generation
    # must answer — the server-owned required set, e.g. [{"question","intent"}].
    picked_questions_json: Mapped[Any | None] = mapped_column(
        json_type(), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class GeoContentItem(
    GeoUUIDPrimaryKeyMixin, GeoScopeMixin, GeoTimestampMixin, Base
):
    """One AI-citable guide piece within a cluster (hub / how-it-works / …)."""

    __tablename__ = "geo_content_items"
    __table_args__ = (
        CheckConstraint(
            "item_type IN ("
            "'hub', 'how_it_works', 'comparison', 'scenario', 'qa', "
            "'question_answer', 'product_spotlight'"
            ")",
            name=conv("ck_geo_items_valid_type"),
        ),
        CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected')",
            name=conv("ck_geo_items_valid_review"),
        ),
        CheckConstraint(
            "generation_status IN ('draft', 'generated', 'failed')",
            name=conv("ck_geo_items_valid_generation"),
        ),
        Index("ix_geo_items_cluster", "cluster_id"),
        Index("ix_geo_items_cluster_type", "cluster_id", "item_type"),
        Index("ix_geo_items_review", "review_status"),
    )

    cluster_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("geo_content_clusters.id", name="fk_geo_items_cluster_id"),
        nullable=False,
    )
    item_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # Structured body: sections + self-contained answer blocks (schema-shaped for
    # AI extraction). Deterministic HTML is rendered at publish time (milestone 2).
    body_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    # Authored SEO: {title, meta_description, url_slug}.
    seo_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    # K product ids this piece names + internal-links to (Rail 1: content → PDP).
    source_product_ids_json: Mapped[Any | None] = mapped_column(
        json_type(), nullable=True
    )
    # Publish-time JSON-LD type for this piece (Article / FAQPage). Milestone 2.
    schema_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Brand/evidence guard verdict, fail-closed (mirrors K brand_audit_json shape).
    brand_audit_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    # Review aid: DeepSeek-flash reading of THIS piece — Chinese translation, what
    # it does for GEO, why it is written that way. Generated automatically, and
    # deliberately fail-open (a missing analysis never blocks content).
    analysis_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    # What a critique-driven rewrite fixed, and what it refused to fake:
    # {round, addressed[], unaddressed[{critique, reason, needs_data, missing_fact}]}.
    # Unaddressed-for-lack-of-data entries become the data gaps to fill in K.
    revision_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    # Where this piece lives once published (WP post id + its permalink). Set from
    # the publisher callback; drives update-in-place instead of duplicate posts.
    wp_post_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    published_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # 线上真实状态。**`published_url` 非空 ≠ 访客看得到**:n8n 首次建文刻意落
    # draft 等人工发布,那一刻 published_url 就已写库;你之后在 WP 点发布,控制台
    # 并不知道。于是产品页反链、批发页挂指南都可能链到草稿 → 访客 404。
    # 由 content_core.wp_sync 批量刷新(一次 API 查全部),消费方只读这一列。
    wp_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    generation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft"
    )
    skill_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class GeoGenerationJob(
    GeoUUIDPrimaryKeyMixin, GeoScopeMixin, GeoTimestampMixin, Base
):
    """Standalone async queue drained by the geo-worker (mirrors k_generation_jobs)."""

    __tablename__ = "geo_generation_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=conv("ck_geo_jobs_valid_status"),
        ),
        Index("ix_geo_jobs_status", "status"),
        Index("ix_geo_jobs_cluster", "cluster_id"),
        Index("ix_geo_jobs_batch", "batch_id"),
        Index("ix_geo_jobs_created", "created_at"),
    )

    cluster_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("geo_content_clusters.id", name="fk_geo_jobs_cluster_id"),
        nullable=False,
    )
    job_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="geo_content"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    batch_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    requested_by_username: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GeoPublishJob(GeoUUIDPrimaryKeyMixin, GeoScopeMixin, GeoTimestampMixin, Base):
    """One dispatch of a cluster's approved articles to WordPress via n8n.

    Mirrors ``PUploadJob`` (queued → dispatched → success | failed, one-time token,
    strictly one in-flight at a time, 15-minute stale reaping) so the two
    publishers behave identically under failure. Unlike P this carries the scope
    triple, because GEO rows are tenant-partitioned.
    """

    __tablename__ = "geo_publish_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'dispatched', 'success', 'failed')",
            name=conv("ck_geo_publish_jobs_valid_status"),
        ),
        Index("ix_geo_publish_jobs_status", "status"),
        Index("ix_geo_publish_jobs_cluster", "cluster_id"),
        Index("ix_geo_publish_jobs_created", "created_at"),
    )

    job_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    cluster_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("geo_content_clusters.id", name="fk_geo_publish_jobs_cluster_id"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="wordpress"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="queued"
    )
    token: Mapped[str] = mapped_column(String(128), nullable=False)
    # [{item_id, wp_post_id, url}] reported back by the publisher.
    published_items_json: Mapped[Any | None] = mapped_column(
        json_type(), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_username: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GeoMinedQuestion(
    GeoUUIDPrimaryKeyMixin, GeoScopeMixin, GeoTimestampMixin, Base
):
    """类目级深挖出来的买家问句。

    **为什么要落表**:原有候选(K 的 FAQ + F 的类目词)是实时读出来的,零成本、
    随时可重算。深挖是**花钱**换来的——一发 Serper 一笔台账——所以必须存下来,
    否则下次进来又是一片空白,等于反复付钱买同一批问句。

    ``depth`` 记的是它从第几层 PAA 挖出来的:0 = 种子直接命中,1 = 二级展开。
    二级的更长尾、竞争更小,恰恰是能打的那批,所以打分时给了加成。
    """

    __tablename__ = "geo_mined_questions"
    __table_args__ = (
        UniqueConstraint(
            "cluster_id",
            "normalized_question",
            name=conv("uq_geo_mined_questions_cluster_norm"),
        ),
        Index("ix_geo_mined_questions_cluster", "cluster_id"),
    )

    cluster_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "geo_content_clusters.id", name=conv("fk_geo_mined_questions_cluster_id")
        ),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_question: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    score: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    seed_query: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GeoWpCategoryMap(Base):
    """Google taxonomy id → WordPress post-category term id.

    The guide categories mirror K's Google taxonomy exactly (owner's ruling), the
    same tree P mirrors into Woo product categories — so products and guides share
    one structure. This is the learned cache that keeps the ensure-path idempotent
    without re-walking WordPress on every publish.
    """

    __tablename__ = "geo_wp_category_map"
    __table_args__ = (
        CheckConstraint(
            "wp_term_id > 0", name=conv("ck_geo_wp_category_map_term_positive")
        ),
        Index("ix_geo_wp_category_map_term", "wp_term_id"),
    )

    google_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    wp_term_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class GeoSiteSetting(Base):
    """Tiny key/value store for site-side ids GEO owns (e.g. the Guides hub page).

    A whole table beats an env var here: the page is created on first publish and
    must be found again on every later one, including from the worker.
    """

    __tablename__ = "geo_site_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


GUIDES_PAGE_ID_KEY = "guides_page_id"


class GeoBacklinkJob(GeoUUIDPrimaryKeyMixin, GeoScopeMixin, GeoTimestampMixin, Base):
    """One dispatch that refreshes the "Learn more" block on live product pages.

    Rail 2 of GEO delivery, kept off the P upload path on purpose: re-running a full
    product upload to change five links would re-upload every image (429 risk) and
    rewrite price, category and schema — an absurd blast radius for a link block.
    This job touches exactly one Woo field, ``description``.

    Same queue semantics as ``GeoPublishJob``/``PUploadJob``: one dispatch in
    flight, commit before send, 15-minute stale reaping, terminal-state idempotency.
    """

    __tablename__ = "geo_backlink_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'dispatched', 'success', 'failed')",
            name=conv("ck_geo_backlink_jobs_valid_status"),
        ),
        Index("ix_geo_backlink_jobs_status", "status"),
        Index("ix_geo_backlink_jobs_created", "created_at"),
    )

    job_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    channel: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="woocommerce"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="queued"
    )
    token: Mapped[str] = mapped_column(String(128), nullable=False)
    # [{product_id, woo_product_id, guide_count}] resolved at dispatch time.
    targets_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    # [{product_id, woo_product_id, updated}] reported back by the workflow.
    updated_items_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_username: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = [
    "GeoBacklinkJob",
    "GeoContentCluster",
    "GeoContentItem",
    "GeoGenerationJob",
    "GeoPublishJob",
    "GeoMinedQuestion",
    "GeoWpCategoryMap",
    "GeoSiteSetting",
    "GUIDES_PAGE_ID_KEY",
]
