"""Mandatory Warehouse rule engine."""

from __future__ import annotations

from dataclasses import dataclass

from r_system_v2.rw.core.models import NormalizedProduct, RuleDecision, RuleEvaluation


@dataclass(frozen=True)
class RuleConfig:
    price_min: float = 25.0
    price_max: float = 70.0
    min_net_margin: float = 0.15
    max_seller_count: int = 15
    max_brand_share: float = 0.50
    blocked_price_trends: tuple[str, ...] = ("declining", "price_war")


class RuleEngine:
    """Apply hard filters before any downstream analysis layer."""

    def __init__(self, config: RuleConfig | None = None) -> None:
        self.config = config or RuleConfig()

    def evaluate(self, product: NormalizedProduct) -> RuleEvaluation:
        checks = {
            "price_band_filter": self.config.price_min <= product.price <= self.config.price_max,
            "margin_check": product.est_net_margin >= self.config.min_net_margin,
            "competition_filter": product.seller_count <= self.config.max_seller_count,
            "brand_dominance_filter": product.brand_share <= self.config.max_brand_share,
            "price_trend_filter": product.price_trend not in self.config.blocked_price_trends,
        }

        reason_map = {
            "price_band_filter": "price_out_of_band",
            "margin_check": "margin_too_low",
            "competition_filter": "too_many_sellers",
            "brand_dominance_filter": "brand_dominance",
            "price_trend_filter": "price_trend_declining",
        }
        reasons = [reason_map[name] for name, passed in checks.items() if not passed]
        decision = RuleDecision.RULE_PASSED if not reasons else RuleDecision.RULE_REJECTED

        return RuleEvaluation(
            asin=product.asin,
            decision=decision,
            reasons=reasons,
            checks=checks,
        )

