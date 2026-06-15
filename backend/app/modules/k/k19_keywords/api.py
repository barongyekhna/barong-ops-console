"""K19-C keyword persistence API layer.

This module exposes KeywordEntry CRUD routes through the K19-B service layer
only. It does not call AI providers, perform SEO analysis, run ranking systems,
directly mutate the store, register application routes, or target
production/staging environments.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from .models import KeywordEntry, KeywordEntrySource, KeywordEntryStatus
from .service import KeywordService

K19_C_MODE = "api_layer"
K19_RUNTIME = "no_execution"
K19_EXTERNAL_ACCESS = False

K19_C_DATA_FLOW = (
    "K19-C API request",
    "K19-B KeywordService",
    "K19-A KeywordEntry",
    "K19-C API response",
)

keyword_router = APIRouter(prefix="/k/keywords", tags=["k-keywords"])


class CreateKeywordRequest(BaseModel):
    """Request payload for creating a human-editable keyword entry."""

    keyword: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    source: KeywordEntrySource
    status: KeywordEntryStatus | None = None


class UpdateKeywordRequest(BaseModel):
    """Request payload for patching a keyword entry."""

    keyword: str | None = Field(default=None, min_length=1)
    product_id: str | None = Field(default=None, min_length=1)
    source: KeywordEntrySource | None = None
    status: KeywordEntryStatus | None = None


class KeywordEntryResponse(BaseModel):
    """Single KeywordEntry response envelope."""

    keyword_entry: KeywordEntry
    status: Literal["created", "updated", "archived"]
    timestamp: datetime


class KeywordListResponse(BaseModel):
    """Product keyword list response envelope."""

    keyword_entries: list[KeywordEntry]
    status: Literal["ok"]
    timestamp: datetime


keyword_service = KeywordService()


@keyword_router.post(
    "",
    response_model=KeywordEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_keyword(payload: CreateKeywordRequest) -> KeywordEntryResponse:
    try:
        keyword_entry = keyword_service.create_from_source(
            product_id=payload.product_id,
            keyword=payload.keyword,
            source=payload.source,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return KeywordEntryResponse(
        keyword_entry=keyword_entry,
        status="created",
        timestamp=datetime.now(UTC),
    )


@keyword_router.get(
    "/{product_id}",
    response_model=KeywordListResponse,
)
def get_keywords_by_product(product_id: str) -> KeywordListResponse:
    return KeywordListResponse(
        keyword_entries=keyword_service.get_by_product(product_id),
        status="ok",
        timestamp=datetime.now(UTC),
    )


@keyword_router.patch(
    "/{keyword_id}",
    response_model=KeywordEntryResponse,
)
def update_keyword(
    keyword_id: str,
    payload: UpdateKeywordRequest,
) -> KeywordEntryResponse:
    keyword_entry = keyword_service.update(
        keyword_id,
        payload.model_dump(exclude_none=True),
    )
    if keyword_entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Keyword entry '{keyword_id}' was not found.",
        )

    return KeywordEntryResponse(
        keyword_entry=keyword_entry,
        status="updated",
        timestamp=datetime.now(UTC),
    )


@keyword_router.delete(
    "/{keyword_id}",
    response_model=KeywordEntryResponse,
)
def delete_keyword(keyword_id: str) -> KeywordEntryResponse:
    keyword_entry = keyword_service.delete(keyword_id)
    if keyword_entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Keyword entry '{keyword_id}' was not found.",
        )

    return KeywordEntryResponse(
        keyword_entry=keyword_entry,
        status="archived",
        timestamp=datetime.now(UTC),
    )


__all__ = [
    "CreateKeywordRequest",
    "K19_C_DATA_FLOW",
    "K19_C_MODE",
    "K19_EXTERNAL_ACCESS",
    "K19_RUNTIME",
    "KeywordEntryResponse",
    "KeywordListResponse",
    "UpdateKeywordRequest",
    "keyword_router",
    "keyword_service",
]
