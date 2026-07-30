"""Pydantic contracts for the store-type layer."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .models import OUTREACH_STATUSES


class StoreTypeCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category_prefix: list[str] = Field(default_factory=list)


class StoreTypeRead(BaseModel):
    """一种店型 + 它现在到底能不能拿去挖客户。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    label: str
    outreach_status: str
    sort_order: int = 0
    notes: str | None = None

    categories: list[StoreTypeCategoryRead] = Field(default_factory=list)
    # 图册成熟度:这个店型能拿出多少个填全了批发价的品。
    total_items: int = 0
    ready_items: int = 0
    prospecting_unlocked: bool = False
    shortfall: int = 0
    # 客户漏斗
    prospects_new: int = 0
    prospects_approved: int = 0
    # 最近才被自动建出来的店型——界面上打个「新」,提醒用户这是上架带出来的。
    newly_added: bool = False


class StoreTypeListResponse(BaseModel):
    store_types: list[StoreTypeRead] = Field(default_factory=list)
    min_ready_items: int = 0
    max_active: int = 1
    active_keys: list[str] = Field(default_factory=list)


class StoreTypeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=2, max_length=64, pattern="^[a-z0-9_]+$")
    label: str = Field(min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)
    sort_order: int = 0


class StoreTypePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)
    sort_order: int | None = None
    outreach_status: str | None = None

    def validated_status(self) -> str | None:
        if self.outreach_status is None:
            return None
        if self.outreach_status not in OUTREACH_STATUSES:
            raise ValueError(f"未知的状态：{self.outreach_status}")
        return self.outreach_status


class StoreTypeCategoryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_prefix: list[str] = Field(min_length=1, max_length=10)
