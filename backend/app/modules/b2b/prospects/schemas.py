"""Pydantic contracts for B2B prospecting."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProspectQueryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_type: str
    store_type_label: str
    country: str
    language: str
    query_template: str
    active: bool


class ProspectQueryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_type: str = Field(min_length=1, max_length=64)
    store_type_label: str = Field(min_length=1, max_length=128)
    country: str = Field(pattern="^(US|CA|MX)$")
    language: str = Field(min_length=2, max_length=5)
    query_template: str = Field(min_length=1, max_length=255)
    active: bool = True

    @field_validator("query_template")
    @classmethod
    def _needs_city_placeholder(cls, value: str) -> str:
        if "{city}" not in value:
            raise ValueError("查询词必须包含 {city} 占位符。")
        return value


class TargetCityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    country: str
    region: str
    city: str
    population: int | None = None
    priority: int
    active: bool


class ProspectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_name: str
    website: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    region: str | None = None
    country: str
    rating: str | None = None
    reviews_count: int | None = None
    store_type: str
    language: str
    source_query: str | None = None
    place_category: str | None = None
    place_cid: str | None = None
    # 自动筛选:用户只读 screen_reason 这一句话
    website_source: str | None = None
    screen_verdict: str | None = None
    screen_reason: str | None = None
    screen_signals: dict | None = None
    # 下面两个是给人工审核用的计算字段,不入库
    maps_url: str | None = None
    chain_hint: str | None = None
    email: str | None = None
    email_verified: bool
    contact_name: str | None = None
    status: str
    reject_reason: str | None = None
    notes: str | None = None
    created_at: datetime


class ProspectListResponse(BaseModel):
    items: list[ProspectRead] = Field(default_factory=list)
    count: int = 0
    new_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    contacted_count: int = 0
    replied_count: int = 0
    customer_count: int = 0


class ProspectReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: bool
    reject_reason: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class SweepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_queries: int = Field(default=50, ge=1, le=500)
    country: str | None = Field(default=None, pattern="^(US|CA|MX)$")
    store_type: str | None = Field(default=None, max_length=64)


class SweepResult(BaseModel):
    queries_executed: int = 0
    places_seen: int = 0
    prospects_created: int = 0
    quota_stopped: bool = False
    quota_used_today: int = 0
    quota_budget: int = 0
    errors: list[str] = Field(default_factory=list)


class ScreenRequest(BaseModel):
    """跑一批自动筛选。"""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    store_type: str | None = Field(default=None, max_length=64)


class ScreenResult(BaseModel):
    screened: int = 0
    fit: int = 0
    unfit: int = 0
    unsure: int = 0
    quota_stopped: bool = False
    quota_used_today: int = 0
    message: str = ""
