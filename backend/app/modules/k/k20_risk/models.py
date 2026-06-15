"""K20-A risk governance data model.

K20-A defines the risk term structure and governance taxonomies only. It does
not run AI detection, apply SEO or ranking logic, execute rules, expose APIs,
or modify upstream K15-K19 systems.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

K20_A_MODE = "risk_data_model_only"
K20_RUNTIME = "disabled"
K20_EXTERNAL_ACCESS = False

RiskLevel = Literal["low", "medium", "high", "critical"]
RiskCategory = Literal[
    "legal",
    "compliance",
    "marketing",
    "safety",
    "platform",
]
RiskTermSource = Literal["K13", "K17", "K18", "manual"]
RiskTermStatus = Literal["active", "resolved", "ignored"]

RISK_LEVEL_DEFINITIONS: dict[RiskLevel, str] = {
    "low": "informational notice",
    "medium": "flag for review",
    "high": "blocking recommendation",
    "critical": "mandatory block for future enforcement",
}

RISK_CATEGORY_DEFINITIONS: dict[RiskCategory, tuple[str, ...]] = {
    "legal": (
        "medical claims",
        "legal claims",
        "guarantee language",
    ),
    "marketing": (
        "exaggerated promotion",
        "best / #1 / guaranteed claims",
    ),
    "compliance": (
        "platform policy terms",
        "ecommerce restricted terms",
    ),
    "safety": (
        "hazardous goods descriptions",
        "prohibited-sale terms",
    ),
    "platform": (
        "marketplace-specific policy signals",
        "listing platform restrictions",
    ),
}

RISK_SOURCE_DEFINITIONS: dict[RiskTermSource, str] = {
    "K13": "AI-detected risk signal",
    "K17": "first-pass filter risk signal",
    "K18": "second-pass validation risk signal",
    "manual": "human-marked risk term",
}

RISK_STATUS_DEFINITIONS: dict[RiskTermStatus, str] = {
    "active": "current unresolved risk term",
    "resolved": "risk term has been addressed",
    "ignored": "risk term has been reviewed and intentionally ignored",
}

K13_TO_K20_MAPPING = {
    "K13 risk_flags[]": "RiskTerm.term",
    "product_id": "RiskTerm.product_id",
    "source": "K13",
    "status": "active",
}

K17_TO_K20_MAPPING = {
    "ChatGPTFilterOutput.risk_flags[]": "RiskTerm.term",
    "ChatGPTFilterOutput.product_id": "RiskTerm.product_id",
    "source": "K17",
    "status": "active",
}

K18_TO_K20_MAPPING = {
    "K18FinalOutput.context.risk_flags[]": "RiskTerm.term",
    "K18FinalOutput.product_id": "RiskTerm.product_id",
    "source": "K18",
    "status": "active",
}

K19_TO_K20_MAPPING = {
    "manual review term": "RiskTerm.term",
    "KeywordEntry.product_id": "RiskTerm.product_id",
    "source": "manual",
    "status": "active",
}


class RiskTerm(BaseModel):
    """Canonical risk governance term entry."""

    id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    term: str = Field(min_length=1)
    risk_level: RiskLevel
    category: RiskCategory
    source: RiskTermSource
    status: RiskTermStatus
    created_at: datetime
    updated_at: datetime

    @field_validator("id", "product_id")
    @classmethod
    def _clean_required_text(cls, value: str) -> str:
        cleaned_value = " ".join(str(value).strip().split())
        if not cleaned_value:
            raise ValueError("value must not be empty")
        return cleaned_value

    @field_validator("term")
    @classmethod
    def _normalize_term(cls, value: str) -> str:
        normalized_term = " ".join(str(value).strip().lower().split())
        if not normalized_term:
            raise ValueError("term must not be empty")
        return normalized_term


__all__ = [
    "K13_TO_K20_MAPPING",
    "K17_TO_K20_MAPPING",
    "K18_TO_K20_MAPPING",
    "K19_TO_K20_MAPPING",
    "K20_A_MODE",
    "K20_EXTERNAL_ACCESS",
    "K20_RUNTIME",
    "RISK_CATEGORY_DEFINITIONS",
    "RISK_LEVEL_DEFINITIONS",
    "RISK_SOURCE_DEFINITIONS",
    "RISK_STATUS_DEFINITIONS",
    "RiskCategory",
    "RiskLevel",
    "RiskTerm",
    "RiskTermSource",
    "RiskTermStatus",
]
