"""流量 ingest 契约。

载荷就是七个 Jetpack 接口的原始响应，一个字段放一个，n8n 打包时不做任何加工。
`extra="ignore"`：Jetpack 响应里多出来的键不会让整批被 422 打回。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TrafficIngestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    site_id: int | None = None
    utc_offset: str | None = Field(default=None, max_length=8)
    collected_at: datetime | None = None
    branches_ok: int | None = None
    visits_day: dict[str, Any] | None = None
    visits_hour: dict[str, Any] | None = None
    top_posts: dict[str, Any] | None = None
    referrers: dict[str, Any] | None = None
    country_views: dict[str, Any] | None = None
    search_terms: dict[str, Any] | None = None
    clicks: dict[str, Any] | None = None


class TrafficIngestResponse(BaseModel):
    days_upserted: int
    hours_upserted: int
    day_from: date | None
    day_to: date | None
    utc_offset: str
    warnings: list[str] = Field(default_factory=list)
