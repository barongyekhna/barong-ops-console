"""主页卡片契约。八张卡、SSE 帧、单卡刷新共用同一个形状。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

HomeCardSeverity = Literal["ok", "warn", "error"]


class HomeCardItem(BaseModel):
    id: str
    title: str
    subtitle: str = ""
    at: datetime | None = None
    href: str = ""


class HomeCardRead(BaseModel):
    card_id: str
    module_key: str | None
    # None = 这一分量降级（比如审批列表语句超时），前端显示「—」而不是 0。
    count: int | None
    items: list[HomeCardItem] = Field(default_factory=list, max_length=5)
    # 内部卡 = 查询时刻；外部卡 = 最近一次采集成功时间。
    freshness: datetime
    actions: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    severity: HomeCardSeverity = "ok"


class HomeBootstrapRead(BaseModel):
    org_type: str
    org_id: str
    cards: list[HomeCardRead]
    poll_seconds: float


class HomeTrafficDay(BaseModel):
    day: date
    views: int
    visitors: int


class HomeTrafficSummaryRead(BaseModel):
    site_utc_offset: str
    day_from: date
    day_to: date
    days: list[HomeTrafficDay]
    views: int
    visitors: int
    prev_views: int
    prev_visitors: int
    today: HomeTrafficDay | None = None
    yesterday: HomeTrafficDay | None = None
    top_post: dict[str, Any] | None = None
    top_referrer: dict[str, Any] | None = None
    top_country: dict[str, Any] | None = None
    collected_at: datetime | None = None
    collector_stale: bool


class HomeTrafficRangeRead(HomeTrafficSummaryRead):
    top_posts: list[dict[str, Any]] = Field(default_factory=list)
    referrers: list[dict[str, Any]] = Field(default_factory=list)
    countries: list[dict[str, Any]] = Field(default_factory=list)
    search_terms: list[dict[str, Any]] = Field(default_factory=list)
    encrypted_search_terms: int = 0
    clicks: list[dict[str, Any]] = Field(default_factory=list)
