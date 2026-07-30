"""Tables for GEO terrain monitoring.

Deliberately small: a question list the operator curates, one row per run, and one
row per (run, question) holding the first page as observed. Keeping the observed
slots means the trend is auditable later — "we were #7 and Reddit was #1" is a
claim you can re-check, "attackability was 62" is not.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
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
from sqlalchemy.types import Uuid

from ....db.base import Base
from ....models.base_mixins import json_type
from ..content.models import GeoScopeMixin, GeoTimestampMixin, GeoUUIDPrimaryKeyMixin


class GeoMonitorQuestion(
    GeoUUIDPrimaryKeyMixin, GeoScopeMixin, GeoTimestampMixin, Base
):
    """A buyer question we watch the search results for.

    Monitored per category (via the cluster), never per SKU — owner's ruling: the
    question a buyer types does not multiply with the number of products.
    """

    __tablename__ = "geo_monitor_questions"
    __table_args__ = (
        Index("ix_geo_monitor_questions_cluster", "cluster_id"),
        Index("ix_geo_monitor_questions_active", "is_active"),
    )

    cluster_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "geo_content_clusters.id", name="fk_geo_monitor_questions_cluster_id"
        ),
        nullable=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 这条监测项是谁的:GEO 的买家问句,还是 SEO 的关键词。
    # **刻意不建第二套表**——"一个查询串的前十名是谁"这件事与它是问句还是
    # 关键词无关,再造一套表等于把 Serper 台账和守门人识别也复制一份,迟早漂。
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="geo_question"
    )
    is_active: Mapped[bool] = mapped_column(
        Integer().with_variant(Integer, "postgresql"),
        nullable=False,
        server_default="1",
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GeoMonitorRun(GeoUUIDPrimaryKeyMixin, GeoScopeMixin, GeoTimestampMixin, Base):
    """One sweep over the active questions."""

    __tablename__ = "geo_monitor_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'failed', 'partial')",
            name="ck_geo_monitor_runs_valid_status",
        ),
        Index("ix_geo_monitor_runs_created", "created_at"),
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="running"
    )
    question_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    checked_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_username: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GeoMonitorResult(GeoUUIDPrimaryKeyMixin, GeoScopeMixin, GeoTimestampMixin, Base):
    """The first page for one question at one point in time."""

    __tablename__ = "geo_monitor_results"
    __table_args__ = (
        Index("ix_geo_monitor_results_run", "run_id"),
        Index("ix_geo_monitor_results_question", "question_id"),
    )

    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("geo_monitor_runs.id", name="fk_geo_monitor_results_run_id"),
        nullable=False,
    )
    question_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "geo_monitor_questions.id", name="fk_geo_monitor_results_question_id"
        ),
        nullable=False,
    )
    # Snapshot: the question text can be edited later, the observation must not move.
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    our_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attackability: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    terrain: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="mixed"
    )
    # [{position, url, title, domain, holder}] — the evidence behind the score.
    results_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    holder_counts_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["GeoMonitorQuestion", "GeoMonitorResult", "GeoMonitorRun"]
