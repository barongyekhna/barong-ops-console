"""K18-A Claude filter data contract.

K18-A defines schemas only. It does not call Claude, ChatGPT, C14, external
providers, API keys, URLs, ranking systems, SEO logic, backend services, or
production/staging environments.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

K18_A_MODE = "schema_only"
K18_RUNTIME = "disabled"
K18_EXTERNAL_ACCESS = False

ClaudeFilterIntent = Literal["k18_second_pass_validation"]
C14ClaudeProvider = Literal["claude"]
C14ClaudeModel = Literal["claude-filter-v1"]
C14ClaudeTask = Literal["second_pass_filter"]
C14ClaudeExecutionMode = Literal["validation_only"]

K18_DATA_FLOW = (
    "K17-F output",
    "K18-A schema",
    "C14 execution (external system)",
    "K18-B (future parsing layer)",
)

K17_TO_K18_MAPPING = {
    "product_id": "product_id",
    "selected_keywords": "keywords",
    "filtered_competitors": "competitors",
    "market_signals": "market_signals",
    "reasoning": "context.reasoning",
    "confidence_score": "context.confidence_score",
    "risk_flags": "context.risk_flags",
}

K17_F_TO_K18_MAPPING = {
    "product_id": "product_id",
    "keywords": "keywords",
    "competitors": "competitors",
    "market_signals": "market_signals",
    "context.reasoning": "context.reasoning",
    "context.confidence": "context.confidence_score",
    "context.risk_flags": "context.risk_flags",
    "intent": "k18_second_pass_validation",
}


class ClaudeFilterContext(BaseModel):
    """K17 reasoning context carried into Claude second-pass validation."""

    reasoning: str = ""
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_flags: list[str] = Field(default_factory=list)


class ClaudeFilterInput(BaseModel):
    """K17-to-K18 input contract for future Claude validation."""

    product_id: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    market_signals: list[str] = Field(default_factory=list)
    context: ClaudeFilterContext
    intent: ClaudeFilterIntent = "k18_second_pass_validation"


class ClaudeFilterOutput(BaseModel):
    """Claude validation result contract for the future K18-B parser."""

    final_keywords: list[str] = Field(default_factory=list)
    validated_competitors: list[str] = Field(default_factory=list)
    market_validation: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_flags: list[str] = Field(default_factory=list)


class C14ClaudeRequest(BaseModel):
    """Structured C14 handoff contract; execution remains external."""

    provider: C14ClaudeProvider = "claude"
    model: C14ClaudeModel = "claude-filter-v1"
    task: C14ClaudeTask = "second_pass_filter"
    input: ClaudeFilterInput
    execution_mode: C14ClaudeExecutionMode = "validation_only"


__all__ = [
    "C14ClaudeExecutionMode",
    "C14ClaudeModel",
    "C14ClaudeProvider",
    "C14ClaudeRequest",
    "C14ClaudeTask",
    "ClaudeFilterContext",
    "ClaudeFilterInput",
    "ClaudeFilterIntent",
    "ClaudeFilterOutput",
    "K17_F_TO_K18_MAPPING",
    "K17_TO_K18_MAPPING",
    "K18_A_MODE",
    "K18_DATA_FLOW",
    "K18_EXTERNAL_ACCESS",
    "K18_RUNTIME",
]
