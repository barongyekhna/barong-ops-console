"""BSR-based monthly sales estimation for R-W product screening."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


ESTIMATOR_VERSION = "bsr_estimate_v2"

_CATEGORY_MULTIPLIERS = (
    (("beauty", "health", "personal care", "美妆", "健康"), 1.25),
    (("toy", "game", "玩具", "游戏"), 1.20),
    (("home", "kitchen", "patio", "lawn", "garden", "家居", "庭院", "花园"), 1.10),
    (("sports", "outdoors", "camping", "运动", "户外", "露营"), 1.00),
    (("office", "办公"), 0.90),
    (("arts", "crafts", "sewing", "手工", "缝纫"), 0.85),
    (("industrial", "scientific", "工具", "家装", "工业"), 0.75),
)


@dataclass(frozen=True)
class MonthlySalesEstimate:
    estimate: int
    minimum: int
    maximum: int
    source: str
    confidence: str
    value: int
    value_source: str
    data_conflict: bool = False
    raw_monthly_sales: int | None = None
    version: str = ESTIMATOR_VERSION

    def to_features(self) -> dict[str, int | str | bool | None]:
        return {
            "monthly_sales_estimate": self.estimate,
            "monthly_sales_estimate_min": self.minimum,
            "monthly_sales_estimate_max": self.maximum,
            "monthly_sales_estimate_source": self.source,
            "monthly_sales_confidence": self.confidence,
            "monthly_sales_value": self.value,
            "monthly_sales_value_source": self.value_source,
            "monthly_sales_data_conflict": self.data_conflict,
            "monthly_sales_raw": self.raw_monthly_sales,
            "monthly_sales_estimator_version": self.version,
        }


def estimate_monthly_sales(
    *,
    bsr: int | None,
    category: str | None = None,
    parent_category_name: str | None = None,
    subcategory_name: str | None = None,
    monthly_sales: int | None = None,
) -> MonthlySalesEstimate:
    """Estimate monthly sales without overwriting true Keepa monthlySold data.

    The model is deliberately conservative: true Keepa values are copied with
    high confidence; otherwise BSR is converted into an approximate range using
    a stable power curve and broad category multipliers.
    """

    rank = _positive_int(bsr)
    parsed_monthly_sales = _positive_int(monthly_sales)
    bsr_estimate = (
        _estimate_from_bsr(
            rank=rank,
            category=category,
            parent_category_name=parent_category_name,
            subcategory_name=subcategory_name,
        )
        if rank is not None
        else None
    )

    if parsed_monthly_sales is not None:
        if bsr_estimate is not None and _monthly_sales_conflicts_with_bsr(
            monthly_sales=parsed_monthly_sales,
            bsr_estimate=bsr_estimate,
            rank=rank,
        ):
            return MonthlySalesEstimate(
                estimate=bsr_estimate.estimate,
                minimum=bsr_estimate.minimum,
                maximum=bsr_estimate.maximum,
                source="bsr_estimate_conflict_with_keepa_monthly_sold",
                confidence="low",
                value=bsr_estimate.estimate,
                value_source="bsr_estimate_conflict_with_keepa_monthly_sold",
                data_conflict=True,
                raw_monthly_sales=parsed_monthly_sales,
            )
        return MonthlySalesEstimate(
            estimate=parsed_monthly_sales,
            minimum=parsed_monthly_sales,
            maximum=parsed_monthly_sales,
            source="keepa_monthly_sold",
            confidence="high",
            value=parsed_monthly_sales,
            value_source="keepa_monthly_sold",
            raw_monthly_sales=parsed_monthly_sales,
        )

    if rank is None:
        return MonthlySalesEstimate(
            estimate=0,
            minimum=0,
            maximum=0,
            source=ESTIMATOR_VERSION,
            confidence="low",
            value=0,
            value_source="unknown",
            raw_monthly_sales=parsed_monthly_sales,
        )

    return bsr_estimate or MonthlySalesEstimate(
        estimate=0,
        minimum=0,
        maximum=0,
        source=ESTIMATOR_VERSION,
        confidence="low",
        value=0,
        value_source="unknown",
        raw_monthly_sales=parsed_monthly_sales,
    )


def _estimate_from_bsr(
    *,
    rank: int,
    category: str | None,
    parent_category_name: str | None,
    subcategory_name: str | None,
) -> MonthlySalesEstimate:
    multiplier = _category_multiplier(
        category=category,
        parent_category_name=parent_category_name,
        subcategory_name=subcategory_name,
    )
    raw_estimate = 12_000 * math.pow(rank, -0.55) * multiplier
    estimate = max(1, int(round(raw_estimate)))
    if rank <= 5_000:
        lower_factor, upper_factor = 0.55, 1.55
        confidence = "medium"
    elif rank <= 20_000:
        lower_factor, upper_factor = 0.45, 1.80
        confidence = "medium"
    elif rank <= 50_000:
        lower_factor, upper_factor = 0.35, 2.25
        confidence = "low"
    else:
        lower_factor, upper_factor = 0.25, 3.00
        confidence = "low"

    return MonthlySalesEstimate(
        estimate=estimate,
        minimum=max(1, int(round(estimate * lower_factor))),
        maximum=max(estimate, int(round(estimate * upper_factor))),
        source=ESTIMATOR_VERSION,
        confidence=confidence,
        value=estimate,
        value_source=ESTIMATOR_VERSION,
    )


def _monthly_sales_conflicts_with_bsr(
    *,
    monthly_sales: int,
    bsr_estimate: MonthlySalesEstimate,
    rank: int | None,
) -> bool:
    if rank is None or monthly_sales <= 0 or bsr_estimate.estimate <= 0:
        return False
    if rank <= 100 and monthly_sales <= 100:
        return True
    if rank <= 500 and monthly_sales <= 150:
        return True
    return bsr_estimate.minimum >= monthly_sales * 3


def _category_multiplier(
    *,
    category: str | None,
    parent_category_name: str | None,
    subcategory_name: str | None,
) -> float:
    text = " ".join(
        part.strip().lower()
        for part in (category, parent_category_name, subcategory_name)
        if isinstance(part, str) and part.strip()
    )
    for terms, multiplier in _CATEGORY_MULTIPLIERS:
        if any(term in text for term in terms):
            return multiplier
    return 1.0


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
