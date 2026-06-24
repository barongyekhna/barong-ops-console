"""Pydantic DTOs for the K Product Knowledge API skeleton."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ....schemas.common import reject_sensitive_data
from .constants import DEFAULT_CANONICAL_LANGUAGE

ReviewStatus = Literal[
    "draft",
    "ai_structured",
    "needs_review",
    "reviewed",
    "approved",
    "blocked",
    "archived",
]
KeywordType = Literal["primary", "secondary", "long_tail", "b2b", "negative", "risk"]
KeywordStatus = Literal["candidate", "approved", "rejected", "removed"]
RiskTermStatus = Literal["candidate", "confirmed", "removed", "false_positive"]


class ProductKnowledgeAttributeItem(BaseModel):
    attribute_key: str = Field(min_length=1, max_length=128)
    attribute_value_text: str | None = None
    attribute_value_json: dict[str, Any] | list[Any] | None = None
    attribute_unit: str | None = Field(default=None, max_length=50)
    attribute_group: str | None = Field(default=None, max_length=128)
    source: str | None = Field(default=None, max_length=100)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    requires_review: bool = False

    @field_validator("attribute_value_json")
    @classmethod
    def validate_attribute_json(cls, value: Any) -> Any:
        return reject_sensitive_data(value)

    @model_validator(mode="after")
    def require_value(self) -> "ProductKnowledgeAttributeItem":
        if self.attribute_value_text is None and self.attribute_value_json is None:
            raise ValueError(
                "At least one of attribute_value_text or attribute_value_json "
                "is required."
            )
        self.attribute_key = self.attribute_key.strip()
        return self


class ProductKnowledgeKeywordItem(BaseModel):
    keyword_text: str = Field(min_length=1, max_length=512)
    keyword_type: KeywordType
    language_code: str = Field(min_length=1, max_length=16)
    market: str | None = Field(default=None, max_length=50)
    search_intent: str | None = Field(default=None, max_length=100)
    source: str = Field(default="unknown", min_length=1, max_length=50)
    status: KeywordStatus = "candidate"
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    reason: str | None = None

    @model_validator(mode="after")
    def normalize_strings(self) -> "ProductKnowledgeKeywordItem":
        self.keyword_text = self.keyword_text.strip()
        self.language_code = self.language_code.strip().lower()
        if self.market is not None:
            self.market = self.market.strip() or None
        return self


class ProductKnowledgeRiskTermItem(BaseModel):
    term_en: str = Field(min_length=1, max_length=512)
    term_zh: str | None = Field(default=None, max_length=512)
    risk_type: str = Field(min_length=1, max_length=100)
    risk_reason: str | None = None
    suggested_action: str | None = None
    source: str = Field(default="unknown", min_length=1, max_length=50)
    status: RiskTermStatus = "candidate"

    @model_validator(mode="after")
    def normalize_strings(self) -> "ProductKnowledgeRiskTermItem":
        self.term_en = self.term_en.strip()
        self.risk_type = self.risk_type.strip()
        return self


class ProductKnowledgeCreate(BaseModel):
    product_key: str = Field(min_length=1, max_length=128)
    raw_input_text: str = Field(min_length=1)
    raw_input_language: str = Field(min_length=1, max_length=16)
    source_system: str | None = Field(default="manual", max_length=100)
    source_record_id: str | None = Field(default=None, max_length=255)
    sku: str | None = Field(default=None, max_length=128)
    product_status: str = Field(default="draft", min_length=1, max_length=50)
    review_status: ReviewStatus = "draft"
    canonical_language: str = Field(
        default=DEFAULT_CANONICAL_LANGUAGE,
        min_length=1,
        max_length=16,
    )
    product_name_en: str | None = Field(default=None, max_length=512)
    brand_name: str | None = Field(default=None, max_length=255)
    manufacturer: str | None = Field(default=None, max_length=255)
    product_type: str | None = Field(default=None, max_length=128)
    short_description_en: str | None = None
    long_description_en: str | None = None
    primary_use_case_en: str | None = None
    target_customer_en: str | None = None
    manual_notes: str | None = None
    attributes: list[ProductKnowledgeAttributeItem] = Field(default_factory=list)
    keywords: list[ProductKnowledgeKeywordItem] = Field(default_factory=list)
    risk_terms: list[ProductKnowledgeRiskTermItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_required_strings(self) -> "ProductKnowledgeCreate":
        self.product_key = self.product_key.strip()
        self.raw_input_language = self.raw_input_language.strip().lower()
        self.canonical_language = self.canonical_language.strip().lower()
        return self


class ProductKnowledgeUpdate(BaseModel):
    source_system: str | None = Field(default=None, max_length=100)
    source_record_id: str | None = Field(default=None, max_length=255)
    sku: str | None = Field(default=None, max_length=128)
    product_status: str | None = Field(default=None, min_length=1, max_length=50)
    review_status: ReviewStatus | None = None
    canonical_language: str | None = Field(default=None, min_length=1, max_length=16)
    raw_input_text: str | None = None
    raw_input_language: str | None = Field(default=None, max_length=16)
    product_name_en: str | None = Field(default=None, max_length=512)
    brand_name: str | None = Field(default=None, max_length=255)
    manufacturer: str | None = Field(default=None, max_length=255)
    product_type: str | None = Field(default=None, max_length=128)
    short_description_en: str | None = None
    long_description_en: str | None = None
    primary_use_case_en: str | None = None
    target_customer_en: str | None = None
    manual_notes: str | None = None

    @model_validator(mode="after")
    def normalize_languages(self) -> "ProductKnowledgeUpdate":
        if self.raw_input_language is not None:
            self.raw_input_language = self.raw_input_language.strip().lower()
        if self.canonical_language is not None:
            self.canonical_language = self.canonical_language.strip().lower()
        return self


class ProductKnowledgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_key: str
    product_status: str
    review_status: str
    canonical_language: str
    raw_input_text: str | None
    raw_input_language: str | None
    product_name_en: str | None
    brand_name: str | None
    manufacturer: str | None
    product_type: str | None
    short_description_en: str | None
    long_description_en: str | None
    primary_use_case_en: str | None
    target_customer_en: str | None
    sku: str | None
    workspace_key: str
    business_context: str
    scope_mode: str
    created_at: datetime
    updated_at: datetime
    attributes_count: int | None = None
    keywords_count: int | None = None
    risk_terms_count: int | None = None


class ProductKnowledgeListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_key: str
    sku: str | None
    product_name_en: str | None
    brand_name: str | None
    product_type: str | None
    product_status: str
    review_status: str
    canonical_language: str
    workspace_key: str
    business_context: str
    scope_mode: str
    created_at: datetime
    updated_at: datetime


class ProductKnowledgeListResponse(BaseModel):
    items: list[ProductKnowledgeListItem]
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class ProductKnowledgeAttributePatch(BaseModel):
    items: list[ProductKnowledgeAttributeItem] = Field(default_factory=list)


class ProductKnowledgeKeywordPatch(BaseModel):
    items: list[ProductKnowledgeKeywordItem] = Field(default_factory=list)


class ProductKnowledgeRiskTermPatch(BaseModel):
    items: list[ProductKnowledgeRiskTermItem] = Field(default_factory=list)


class ProductKnowledgeAttributeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    attribute_key: str
    attribute_value_text: str | None
    attribute_value_json: dict[str, Any] | list[Any] | None
    attribute_unit: str | None
    attribute_group: str | None
    source: str | None
    confidence: Decimal | None
    requires_review: bool
    reviewed_by_user_id: UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProductKnowledgeAttributeListResponse(BaseModel):
    items: list[ProductKnowledgeAttributeRead]
    count: int = Field(ge=0)


class ProductKnowledgeKeywordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    keyword_text: str
    keyword_type: str
    language_code: str
    market: str | None
    search_intent: str | None
    source: str
    status: str
    confidence: Decimal | None
    reason: str | None
    reviewed_by_user_id: UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProductKnowledgeKeywordListResponse(BaseModel):
    items: list[ProductKnowledgeKeywordRead]
    count: int = Field(ge=0)


class ProductKnowledgeRiskTermRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    term_en: str
    term_zh: str | None
    risk_type: str
    risk_reason: str | None
    suggested_action: str | None
    source: str
    status: str
    confirmed_by_user_id: UUID | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProductKnowledgeRiskTermListResponse(BaseModel):
    items: list[ProductKnowledgeRiskTermRead]
    count: int = Field(ge=0)


class ArchiveProductKnowledgeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class ErrorResponse(BaseModel):
    code: str
    message: str
