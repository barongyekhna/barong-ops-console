"""K17-A ChatGPT filter data contract.

K17-A defines structured input/output schemas only. It does not execute AI
calls, perform filtering, apply ranking or SEO logic, expose API routes, mutate
K16 data, or target production/staging environments.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.modules.k.k16_serp.models import SERPItem, SERPResult

K17_A_MODE = "contract_only"
K17_RUNTIME = "disabled"
K17_EXTERNAL_ACCESS = False

ChatGPTFilterIntent = Literal["structured_for_chatgpt"]

K17_CONTRACT_FLOW = (
    "k16_serp_result",
    "k17_chatgpt_filter_contract",
    "future_c14_chatgpt_execution",
    "k18_consumer",
)


class ChatGPTFilterInput(BaseModel):
    """Structured K16-to-K17 input contract for future ChatGPT filtering."""

    serp_bundle: SERPResult
    product_context: dict[str, Any] = Field(default_factory=dict)
    market: str = Field(min_length=1)
    query: str = Field(min_length=1)
    filter_mode: str = Field(default="strict", min_length=1)
    keywords: list[str] = Field(default_factory=list)
    organic_results: list[SERPItem] = Field(default_factory=list)
    competitor_links: list[str] = Field(default_factory=list)
    intent: ChatGPTFilterIntent = "structured_for_chatgpt"


class ChatGPTFilterOutput(BaseModel):
    """Structured K17 output contract for K18 consumption."""

    selected_keywords: list[str] = Field(default_factory=list)
    filtered_competitors: list[str] = Field(default_factory=list)
    market_signals: list[str] = Field(default_factory=list)
    reasoning: str = ""
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_flags: list[str] = Field(default_factory=list)


__all__ = [
    "ChatGPTFilterInput",
    "ChatGPTFilterOutput",
    "ChatGPTFilterIntent",
    "K17_CONTRACT_FLOW",
    "K17_A_MODE",
    "K17_RUNTIME",
    "K17_EXTERNAL_ACCESS",
]
