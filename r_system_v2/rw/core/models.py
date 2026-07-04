"""Shared data contracts for the R-W Warehouse module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ProductState(str, Enum):
    DISCOVERED = "discovered"
    ENRICHED = "enriched"
    RULE_PASSED = "rule_passed"
    AI1_PASSED = "ai1_passed"
    AI1_REJECTED = "ai1_rejected"
    REJECTED = "rejected"


class RuleDecision(str, Enum):
    RULE_PASSED = "rule_passed"
    RULE_REJECTED = "rule_rejected"


@dataclass(frozen=True)
class IngestionRecord:
    asin: str
    source_query: str
    marketplace: str = "US"
    category_id: str | None = None
    state: ProductState = ProductState.DISCOVERED
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


@dataclass(frozen=True)
class KeepaProductData:
    asin: str
    price: float
    bsr: int
    reviews: int
    seller_count: int
    category: str
    title: str
    brand: str
    landed_cost: float | None
    brand_share: float
    price_trend: str
    marketplace: str = "US"
    rating: float | None = None
    image_url: str | None = None
    fulfillment_method: str | None = None
    lithium_battery_warning: bool = False
    margin_source: str | None = None
    margin_confidence: str | None = None
    monthly_sales: int | None = None
    parent_category_rank: int | None = None
    parent_category_name: str | None = None
    subcategory_rank: int | None = None
    subcategory_name: str | None = None
    mock_generated: bool = True
    fetched_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedProduct:
    asin: str
    source_query: str
    marketplace: str
    title: str
    brand: str
    category: str
    price: float
    bsr: int
    reviews: int
    seller_count: int
    landed_cost: float | None
    est_net_margin: float | None
    brand_share: float
    price_trend: str
    rating: float | None
    title_zh: str | None = None
    title_zh_source: str | None = None
    title_zh_updated_at: str | None = None
    image_url: str | None = None
    fulfillment_method: str | None = None
    lithium_battery_warning: bool = False
    margin_source: str | None = None
    margin_confidence: str | None = None
    category_id: str | None = None
    category_path: list[str] = field(default_factory=list)
    skill_score: int | None = None
    state: ProductState = ProductState.ENRICHED
    rule_reject_reason: str | None = None
    features: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def transition_to(self, target: ProductState) -> None:
        allowed = {
            ProductState.DISCOVERED: {ProductState.ENRICHED},
            ProductState.ENRICHED: {ProductState.RULE_PASSED, ProductState.REJECTED},
            ProductState.RULE_PASSED: {ProductState.AI1_PASSED, ProductState.AI1_REJECTED},
            ProductState.AI1_PASSED: set(),
            ProductState.AI1_REJECTED: set(),
            ProductState.REJECTED: set(),
        }
        if target not in allowed[self.state]:
            raise ValueError(f"invalid state transition: {self.state.value} -> {target.value}")
        self.state = target
        self.updated_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


@dataclass(frozen=True)
class RuleEvaluation:
    asin: str
    decision: RuleDecision
    reasons: list[str]
    checks: dict[str, bool]
    evaluated_at: str = field(default_factory=utc_now_iso)

    @property
    def passed(self) -> bool:
        return self.decision is RuleDecision.RULE_PASSED

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decision"] = self.decision.value
        return data


@dataclass(frozen=True)
class DeepSeekScreening:
    asin: str
    score: int
    verdict: str
    competition_attackability: int
    demand_quality: int
    top_reason: str
    channel_guess: str
    strict_json: dict[str, Any]
    skill_loaded: bool
    quant_filter_enabled: bool
    rule_based_scoring_active: bool
    output_schema_strict_json: bool
    evaluated_at: str = field(default_factory=utc_now_iso)

    @property
    def passed(self) -> bool:
        return self.score >= 60 or self.verdict == "hold"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    asin: str
    ingestion: IngestionRecord
    keepa_data: KeepaProductData
    product: NormalizedProduct
    rule_evaluation: RuleEvaluation
    deepseek_screening: DeepSeekScreening | None
    transitions: list[str]
    latency_ms: float

    @property
    def success(self) -> bool:
        return self.product.state in {
            ProductState.AI1_PASSED,
            ProductState.AI1_REJECTED,
            ProductState.REJECTED,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "asin": self.asin,
            "ingestion": self.ingestion.to_dict(),
            "keepa_data": self.keepa_data.to_dict(),
            "product": self.product.to_dict(),
            "rule_evaluation": self.rule_evaluation.to_dict(),
            "deepseek_screening": (
                self.deepseek_screening.to_dict() if self.deepseek_screening else None
            ),
            "transitions": self.transitions,
            "latency_ms": self.latency_ms,
            "success": self.success,
        }
