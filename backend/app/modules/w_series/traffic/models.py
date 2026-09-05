"""独立站流量表。

两张表都按 (workspace_key, 日期/小时桶) 唯一，每轮采集用 upsert 重写最近 30 天，
所以历史日期会被 Jetpack 的最终数自动修正，不会累积重复行。

`day` 是 Jetpack 按**站点时区**分好的自然日，原样入库不做二次换算——
控制台若按自己的时区重新分日，就永远和 WordPress 后台的数字对不上。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from ....db.base import Base
from ....models.base_mixins import json_type


class WTrafficDaily(Base):
    __tablename__ = "w_traffic_daily"
    __table_args__ = (
        UniqueConstraint("workspace_key", "day", name="uq_w_traffic_daily_ws_day"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_key: Mapped[str] = mapped_column(String(128), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    views: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    visitors: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    top_posts_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        json_type(), nullable=True
    )
    referrers_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        json_type(), nullable=True
    )
    countries_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        json_type(), nullable=True
    )
    search_terms_json: Mapped[dict[str, Any] | None] = mapped_column(
        json_type(), nullable=True
    )
    clicks_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        json_type(), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class WTrafficHourly(Base):
    __tablename__ = "w_traffic_hourly"
    __table_args__ = (
        UniqueConstraint(
            "workspace_key", "bucket_at", name="uq_w_traffic_hourly_ws_bucket"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workspace_key: Mapped[str] = mapped_column(String(128), nullable=False)
    bucket_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    views: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    visitors: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
