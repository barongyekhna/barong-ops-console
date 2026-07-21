"""Validated API contracts for the W-S product source library."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .product_sources import normalize_sku


class ProductSourceUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The path remains authoritative.  Accepting this optional mirror keeps
    # full-row editor payloads compatible while still detecting key mismatch.
    sku: str | None = Field(default=None, max_length=64)
    source_url: str = Field(min_length=1, max_length=1000)
    supplier_name: str | None = Field(default=None, max_length=200)
    unit_cost: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
    )
    currency: str = Field(default="CNY", min_length=1, max_length=8)
    moq: int | None = Field(default=None, ge=1)
    notes: str | None = None

    @field_validator("sku", mode="before")
    @classmethod
    def _normalize_optional_sku(cls, value: Any) -> Any:
        if value is None:
            return None
        normalized = normalize_sku(value)
        if not normalized:
            raise ValueError("sku must not be blank")
        return normalized

    @field_validator("source_url", mode="before")
    @classmethod
    def _trim_source_url(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("source_url")
    @classmethod
    def _validate_source_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
        except ValueError as exc:
            raise ValueError("source_url must be a valid HTTP(S) URL") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be a valid HTTP(S) URL")
        return value

    @field_validator("supplier_name", "notes", mode="before")
    @classmethod
    def _trim_optional_text(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return value.strip().upper()


class ProductSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    source_url: str
    supplier_name: str | None
    unit_cost: Decimal | None
    currency: str
    moq: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ProductSourceListResponse(BaseModel):
    items: list[ProductSourceRead]
    page: int
    page_size: int
    total: int
    pages: int


__all__ = [
    "ProductSourceListResponse",
    "ProductSourceRead",
    "ProductSourceUpsertRequest",
]
