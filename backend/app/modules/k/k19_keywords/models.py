"""K19-A keyword entry data model.

K19-A defines the human-editable keyword asset structure only. It does not call
AI providers, run keyword ranking, perform SEO analysis, invoke K17/K18 logic,
implement services or APIs, or target production/staging environments.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

K19_A_MODE = "data_model_only"
K19_RUNTIME = "disabled"
K19_EXTERNAL_ACCESS = False

KeywordEntrySource = Literal["K15", "K16", "K17", "K18", "manual"]
KeywordEntryStatus = Literal["active", "archived", "suggested", "edited"]

KEYWORD_SOURCE_DEFINITIONS = {
    "K15": "research",
    "K16": "SERP",
    "K17": "ChatGPT filtered",
    "K18": "Claude validated",
    "manual": "human input",
}

KEYWORD_STATUS_DEFINITIONS = {
    "active": "current valid keyword",
    "archived": "discarded keyword",
    "suggested": "AI-suggested keyword pending human confirmation",
    "edited": "keyword modified by a human",
}

K15_TO_K19_MAPPING = {
    "ResearchRun.keywords[]": "KeywordEntry.keyword",
    "ResearchRun.product_id": "KeywordEntry.product_id",
    "source": "K15",
    "status": "suggested",
}

K16_TO_K19_MAPPING = {
    "SERPResult.keywords[]": "KeywordEntry.keyword",
    "SERPResult.product_id": "KeywordEntry.product_id",
    "source": "K16",
    "status": "suggested",
}

K17_TO_K19_MAPPING = {
    "ChatGPTFilterOutput.selected_keywords[]": "KeywordEntry.keyword",
    "source": "K17",
    "status": "suggested",
}

K18_TO_K19_MAPPING = {
    "K18FinalOutput.keywords[]": "KeywordEntry.keyword",
    "source": "K18",
    "status": "active",
}


class KeywordEntry(BaseModel):
    """Canonical human-editable keyword asset entry."""

    id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    keyword: str = Field(min_length=1)
    source: KeywordEntrySource
    status: KeywordEntryStatus
    created_at: datetime
    updated_at: datetime

    @field_validator("id", "product_id")
    @classmethod
    def _clean_required_text(cls, value: str) -> str:
        cleaned_value = " ".join(str(value).strip().split())
        if not cleaned_value:
            raise ValueError("value must not be empty")
        return cleaned_value

    @field_validator("keyword")
    @classmethod
    def _normalize_keyword(cls, value: str) -> str:
        normalized_keyword = " ".join(str(value).strip().lower().split())
        if not normalized_keyword:
            raise ValueError("keyword must not be empty")
        return normalized_keyword


__all__ = [
    "K15_TO_K19_MAPPING",
    "K16_TO_K19_MAPPING",
    "K17_TO_K19_MAPPING",
    "K18_TO_K19_MAPPING",
    "K19_A_MODE",
    "K19_EXTERNAL_ACCESS",
    "K19_RUNTIME",
    "KEYWORD_SOURCE_DEFINITIONS",
    "KEYWORD_STATUS_DEFINITIONS",
    "KeywordEntry",
    "KeywordEntrySource",
    "KeywordEntryStatus",
]
