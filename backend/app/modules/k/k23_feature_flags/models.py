"""K23-A feature flag data model.

K23-A defines the feature flag structure and taxonomy only. It does not
evaluate flags, implement runtime systems, expose services or APIs, render UI,
call external systems, apply AI/SEO/ranking logic, or target production/staging
environments.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

K23_A_MODE = "data_model_only"
K23_RUNTIME = "disabled"
K23_EXTERNAL_ACCESS = False

FeatureFlagScope = Literal["global", "module", "product", "user"]
FeatureFlagModule = Literal[
    "K13",
    "K14",
    "K15",
    "K16",
    "K17",
    "K18",
    "K19",
    "K20",
    "K23",
]

FEATURE_FLAG_SCOPE_DEFINITIONS: dict[FeatureFlagScope, str] = {
    "global": "affects the entire system",
    "module": "affects one K-series module",
    "product": "controls behavior for one product",
    "user": "reserved for future per-user control",
}

FEATURE_FLAG_MODULE_DEFINITIONS: dict[FeatureFlagModule, str] = {
    "K13": "AI analysis bridge module",
    "K14": "selling points module",
    "K15": "research runs module",
    "K16": "SERP module",
    "K17": "ChatGPT filter contract module",
    "K18": "Claude filter contract module",
    "K19": "keyword governance module",
    "K20": "risk governance module",
    "K23": "feature flag contract module",
}

FEATURE_FLAG_FALLBACK_DEFINITION = (
    "fallback_value is the default boolean value used by a future evaluator when "
    "a flag key is missing; K23-A only defines the field."
)


class FeatureFlag(BaseModel):
    """Canonical feature flag contract entry."""

    id: str = Field(min_length=1)
    key: str = Field(min_length=1)
    enabled: bool
    scope: FeatureFlagScope
    module: FeatureFlagModule
    description: str = Field(default="")
    fallback_value: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("id")
    @classmethod
    def _clean_required_text(cls, value: str) -> str:
        cleaned_value = " ".join(str(value).strip().split())
        if not cleaned_value:
            raise ValueError("value must not be empty")
        return cleaned_value

    @field_validator("key")
    @classmethod
    def _normalize_key(cls, value: str) -> str:
        normalized_key = "_".join(str(value).strip().lower().split())
        if not normalized_key:
            raise ValueError("key must not be empty")
        return normalized_key

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str) -> str:
        return " ".join(str(value).strip().split())


__all__ = [
    "FEATURE_FLAG_FALLBACK_DEFINITION",
    "FEATURE_FLAG_MODULE_DEFINITIONS",
    "FEATURE_FLAG_SCOPE_DEFINITIONS",
    "FeatureFlag",
    "FeatureFlagModule",
    "FeatureFlagScope",
    "K23_A_MODE",
    "K23_EXTERNAL_ACCESS",
    "K23_RUNTIME",
]
