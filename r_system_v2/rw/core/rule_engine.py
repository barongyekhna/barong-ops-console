"""Mandatory Warehouse rule engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from r_system_v2.rw.core.models import NormalizedProduct, RuleDecision, RuleEvaluation


@dataclass(frozen=True)
class RuleConfig:
    price_min: float = 25.0
    price_max: float = 70.0
    min_net_margin: float = 0.15
    max_brand_share: float = 0.50
    max_top3_reviews: int = 500
    max_weight_lb: float = 2.0
    blocked_price_trends: tuple[str, ...] = ("declining", "price_war")
    redline_terms: tuple[str, ...] = (
        "medical",
        "knife",
        "restricted",
        "fda",
        "children safety",
        "医疗",
        "刀",
        "强制认证",
        "侵权",
    )


class RuleEngine:
    """Apply hard filters before any downstream analysis layer."""

    def __init__(self, config: RuleConfig | None = None) -> None:
        self.config = config or RuleConfig()

    def evaluate(self, product: NormalizedProduct) -> RuleEvaluation:
        top3_review_count = _optional_int_feature(product.features, "top3_review_count")
        weight_lb = _optional_float_feature(product.features, "weight_lb")
        viral_suspect = _optional_bool_feature(product.features, "viral_suspect")
        redline_category = _optional_bool_feature(product.features, "redline_category")
        checks = {
            "price_band_filter": self.config.price_min <= product.price <= self.config.price_max,
            "margin_check": (
                product.est_net_margin is None
                or product.est_net_margin >= self.config.min_net_margin
            ),
            "brand_dominance_filter": product.brand_share <= self.config.max_brand_share,
            "price_trend_filter": product.price_trend not in self.config.blocked_price_trends,
            "review_wall_filter": (
                top3_review_count is None
                or top3_review_count <= self.config.max_top3_reviews
            ),
            "viral_filter": viral_suspect is not True,
            "weight_filter": weight_lb is None or weight_lb <= self.config.max_weight_lb,
            "redline_filter": (
                redline_category is not True
                and not _matches_redline(product, self.config.redline_terms)
            ),
        }

        reason_map = {
            "price_band_filter": "price_out_of_band",
            "margin_check": "margin_too_low",
            "brand_dominance_filter": "brand_dominance",
            "price_trend_filter": "price_trend_declining",
            "review_wall_filter": "review_wall_too_high",
            "viral_filter": "viral_unproven",
            "weight_filter": "too_heavy",
            "redline_filter": "redline_category",
        }
        reasons = [reason_map[name] for name, passed in checks.items() if not passed]
        decision = RuleDecision.RULE_PASSED if not reasons else RuleDecision.RULE_REJECTED

        return RuleEvaluation(
            asin=product.asin,
            decision=decision,
            reasons=reasons,
            checks=checks,
        )


def _optional_int_feature(features: dict[str, Any], key: str) -> int | None:
    value = features.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float_feature(features: dict[str, Any], key: str) -> float | None:
    value = features.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool_feature(features: dict[str, Any], key: str) -> bool | None:
    value = features.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return None


def _matches_redline(product: NormalizedProduct, terms: tuple[str, ...]) -> bool:
    haystack = " ".join(
        [
            product.title,
            product.brand,
            product.category,
            " ".join(product.category_path),
        ]
    ).lower()
    return any(term.lower() in haystack for term in terms)
