"""工艺事实库的三张表。

设计要点全部围绕一件事:**事实会变,而已发布的内容不会自己跟着变**。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
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

FACT_STATUSES = ("draft", "approved", "retired")


class _ScopeMixin:
    """与 K/GEO 同一套 scope 三元组,好复用 apply_scope_filters。"""

    workspace_key: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default="default_independent_store"
    )
    business_context: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="independent_store"
    )
    scope_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="adapter_pending"
    )


class _StampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CraftFact(_ScopeMixin, _StampMixin, Base):
    """一条可核的工艺事实。**只有 approved 的才允许进内容。**

    ``claim`` 是一句能被引用的陈述("主体密封为双道 O 圈 + 超声波焊接");
    ``value``/``unit`` 抽出可测量的部分,好喂进接地语料让护栏认得。
    ``basis`` 记依据(自测/供应商规格/标准号)——没有依据的"事实"不是事实。
    """

    __tablename__ = "craft_facts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'approved', 'retired')",
            name=conv("ck_craft_facts_valid_status"),
        ),
        CheckConstraint("version >= 1", name=conv("ck_craft_facts_version_positive")),
        Index("ix_craft_facts_topic", "topic"),
        Index("ix_craft_facts_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # 归类用,如 waterproof-sealing / lithium-pack / injection-molding。
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 这条事实凭什么成立。空 basis 的事实不许批准。
    basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="draft"
    )
    # 每次实质性修改 +1。引用台账记的是**当时的版本**,所以能算出谁过期了。
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # 可选:这条工艺用在哪些 K 产品上(便于从事实反查产品页)。
    product_ids_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CraftFactRevision(_StampMixin, Base):
    """每个版本的快照。**改了什么、谁改的、为什么**——事后能查。

    不是审计洁癖:工艺改了以后要判断"引用旧版的那篇文章还能不能用",必须看得到
    旧版原文。
    """

    __tablename__ = "craft_fact_revisions"
    __table_args__ = (
        UniqueConstraint("fact_id", "version", name=conv("uq_craft_fact_revision")),
        Index("ix_craft_fact_revisions_fact", "fact_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    fact_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("craft_facts.id", name=conv("fk_craft_fact_revisions_fact_id")),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # 该版本的完整字段快照。
    snapshot_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ContentFactUsage(_StampMixin, Base):
    """哪篇内容引用了哪条事实的**哪个版本**。

    这张表是"过期告警"的全部依据:``usage.fact_version < fact.version`` 就说明
    那篇内容引用的是旧版。没有它,工艺一改就只能靠人肉回忆哪些文章要改。

    ``content_kind`` 让 GEO / SEO / B2B 共用一张表,不各建一份。
    """

    __tablename__ = "content_fact_usage"
    __table_args__ = (
        UniqueConstraint(
            "content_kind",
            "content_id",
            "fact_id",
            name=conv("uq_content_fact_usage"),
        ),
        Index("ix_content_fact_usage_fact", "fact_id"),
        Index("ix_content_fact_usage_content", "content_kind", "content_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # 'geo_item' / 'seo_item' / 'b2b_page' …
    content_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fact_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("craft_facts.id", name=conv("fk_content_fact_usage_fact_id")),
        nullable=False,
    )
    # 引用当时的版本。与 fact.version 一比就知道有没有过期。
    fact_version: Mapped[int] = mapped_column(Integer, nullable=False)


__all__ = ["FACT_STATUSES", "ContentFactUsage", "CraftFact", "CraftFactRevision"]
