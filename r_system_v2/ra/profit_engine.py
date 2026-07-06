"""Deterministic R-A profit calculation for the US Amazon market."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


REFERRAL_FEE_RATE = Decimal("0.15")
SELLER_RECEIPT_RATE = Decimal("0.85")
FIRST_MILE_CNY_PER_KG = Decimal("8")
DEFAULT_USD_CNY_RATE = Decimal("7.20")
DEFAULT_MIN_GROSS_MARGIN = Decimal("0.15")
FORMULA_VERSION = "ra_us_gross_profit_v1"


@dataclass(frozen=True)
class ProfitInput:
    asin: str
    sell_price_usd: Decimal | None
    fba_fee_usd: Decimal | None
    unit_price_cny: Decimal | None
    domestic_shipping_cny: Decimal | None
    actual_weight_kg: Decimal | None
    length_cm: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None
    exchange_rate_usd_cny: Decimal = DEFAULT_USD_CNY_RATE
    min_gross_margin: Decimal = DEFAULT_MIN_GROSS_MARGIN
    marketplace: str = "US"


@dataclass(frozen=True)
class ProfitResult:
    asin: str
    verdict: str
    confidence: str
    sell_price_usd: Decimal | None
    amazon_referral_fee_usd: Decimal | None
    fba_fee_usd: Decimal | None
    unit_price_usd: Decimal | None
    domestic_shipping_usd: Decimal | None
    first_mile_freight_usd: Decimal | None
    landed_cost_usd: Decimal | None
    amazon_fees_usd: Decimal | None
    gross_profit_usd: Decimal | None
    gross_margin: Decimal | None
    roi: Decimal | None
    actual_weight_kg: Decimal | None
    volume_weight_kg: Decimal | None
    chargeable_weight_kg: Decimal | None
    first_mile_freight_cny: Decimal | None
    exchange_rate_usd_cny: Decimal
    min_gross_margin: Decimal
    warnings: tuple[str, ...]
    blocked_reasons: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "formula_version": FORMULA_VERSION,
            "marketplace": "US",
            "formula": "售价*0.85 - 头程运费 - FBA费用 - 供应商产品成本 - 供应商国内运费",
            "referral_fee_rate": _number(REFERRAL_FEE_RATE),
            "seller_receipt_rate": _number(SELLER_RECEIPT_RATE),
            "first_mile_cny_per_kg": _number(FIRST_MILE_CNY_PER_KG),
            "exchange_rate_usd_cny": _number(self.exchange_rate_usd_cny),
            "min_gross_margin": _number(self.min_gross_margin),
            "sell_price_usd": _number(self.sell_price_usd),
            "amazon_referral_fee_usd": _number(self.amazon_referral_fee_usd),
            "fba_fee_usd": _number(self.fba_fee_usd),
            "unit_price_usd": _number(self.unit_price_usd),
            "domestic_shipping_usd": _number(self.domestic_shipping_usd),
            "first_mile_freight_usd": _number(self.first_mile_freight_usd),
            "landed_cost_usd": _number(self.landed_cost_usd),
            "landed_cost_cny": _number(
                _usd_to_cny(self.landed_cost_usd, self.exchange_rate_usd_cny)
            ),
            "amazon_fees_usd": _number(self.amazon_fees_usd),
            "gross_profit_usd": _number(self.gross_profit_usd),
            "gross_profit_cny": _number(
                _usd_to_cny(self.gross_profit_usd, self.exchange_rate_usd_cny)
            ),
            "gross_margin": _number(self.gross_margin),
            "roi": _number(self.roi),
            "actual_weight_kg": _number(self.actual_weight_kg),
            "volume_weight_kg": _number(self.volume_weight_kg),
            "chargeable_weight_kg": _number(self.chargeable_weight_kg),
            "first_mile_freight_cny": _number(self.first_mile_freight_cny),
            "verdict": self.verdict,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "blocked_reasons": list(self.blocked_reasons),
        }


def calculate_us_profit(inputs: ProfitInput) -> ProfitResult:
    warnings: list[str] = []
    blocked: list[str] = []
    marketplace = inputs.marketplace.upper()
    if marketplace != "US":
        blocked.append("当前利润公式仅支持美国站。")

    sell_price = _positive(inputs.sell_price_usd)
    fba_fee = _non_negative(inputs.fba_fee_usd)
    unit_price_cny = _positive(inputs.unit_price_cny)
    domestic_shipping_cny = _non_negative(inputs.domestic_shipping_cny) or Decimal("0")
    exchange_rate = _positive(inputs.exchange_rate_usd_cny) or DEFAULT_USD_CNY_RATE
    min_margin = _non_negative(inputs.min_gross_margin) or DEFAULT_MIN_GROSS_MARGIN

    if sell_price is None:
        blocked.append("缺少亚马逊售价。")
    if fba_fee is None:
        blocked.append("缺少 Keepa FBA fee。")
    if unit_price_cny is None:
        blocked.append("缺少供应商产品成本。")
    if inputs.domestic_shipping_cny is None:
        warnings.append("未获取供应商国内运费提醒，暂按 0 元计入。")

    volume_weight = _volume_weight_kg(inputs.length_cm, inputs.width_cm, inputs.height_cm)
    actual_weight = _positive(inputs.actual_weight_kg)
    chargeable_weight = _chargeable_weight(actual_weight, volume_weight)
    if chargeable_weight is None:
        blocked.append("缺少可用于头程计算的实际重量或尺寸。")
    elif volume_weight is None:
        warnings.append("缺少完整尺寸，头程只按实际重量计算。")
    elif actual_weight is None:
        warnings.append("缺少实际重量，头程只按体积重计算。")

    amazon_referral_fee = _q2(sell_price * REFERRAL_FEE_RATE) if sell_price is not None else None
    unit_price_usd = _q2(unit_price_cny / exchange_rate) if unit_price_cny is not None else None
    domestic_shipping_usd = _q2(domestic_shipping_cny / exchange_rate)
    first_mile_cny = (
        _q2(chargeable_weight * FIRST_MILE_CNY_PER_KG)
        if chargeable_weight is not None
        else None
    )
    first_mile_usd = _q2(first_mile_cny / exchange_rate) if first_mile_cny is not None else None

    if blocked:
        return ProfitResult(
            asin=inputs.asin,
            verdict="blocked",
            confidence="blocked",
            sell_price_usd=_q2_or_none(sell_price),
            amazon_referral_fee_usd=amazon_referral_fee,
            fba_fee_usd=_q2_or_none(fba_fee),
            unit_price_usd=unit_price_usd,
            domestic_shipping_usd=domestic_shipping_usd,
            first_mile_freight_usd=first_mile_usd,
            landed_cost_usd=None,
            amazon_fees_usd=None,
            gross_profit_usd=None,
            gross_margin=None,
            roi=None,
            actual_weight_kg=_q4_or_none(actual_weight),
            volume_weight_kg=_q4_or_none(volume_weight),
            chargeable_weight_kg=_q4_or_none(chargeable_weight),
            first_mile_freight_cny=first_mile_cny,
            exchange_rate_usd_cny=exchange_rate,
            min_gross_margin=min_margin,
            warnings=tuple(warnings),
            blocked_reasons=tuple(blocked),
        )

    assert sell_price is not None
    assert fba_fee is not None
    assert unit_price_usd is not None
    assert first_mile_usd is not None
    landed_cost = _q2(unit_price_usd + domestic_shipping_usd + first_mile_usd)
    amazon_fees = _q2(amazon_referral_fee + fba_fee)  # type: ignore[operator]
    gross_profit = _q2(sell_price * SELLER_RECEIPT_RATE - first_mile_usd - fba_fee - unit_price_usd - domestic_shipping_usd)
    gross_margin = _q4(gross_profit / sell_price)
    roi = _q4(gross_profit / landed_cost) if landed_cost > 0 else None
    verdict = "pass" if gross_margin >= min_margin else "reject"
    confidence = "medium" if warnings else "high"

    return ProfitResult(
        asin=inputs.asin,
        verdict=verdict,
        confidence=confidence,
        sell_price_usd=_q2(sell_price),
        amazon_referral_fee_usd=amazon_referral_fee,
        fba_fee_usd=_q2(fba_fee),
        unit_price_usd=unit_price_usd,
        domestic_shipping_usd=domestic_shipping_usd,
        first_mile_freight_usd=first_mile_usd,
        landed_cost_usd=landed_cost,
        amazon_fees_usd=amazon_fees,
        gross_profit_usd=gross_profit,
        gross_margin=gross_margin,
        roi=roi,
        actual_weight_kg=_q4_or_none(actual_weight),
        volume_weight_kg=_q4_or_none(volume_weight),
        chargeable_weight_kg=_q4_or_none(chargeable_weight),
        first_mile_freight_cny=first_mile_cny,
        exchange_rate_usd_cny=exchange_rate,
        min_gross_margin=min_margin,
        warnings=tuple(warnings),
        blocked_reasons=(),
    )


def decimal_value(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _volume_weight_kg(
    length_cm: Decimal | None,
    width_cm: Decimal | None,
    height_cm: Decimal | None,
) -> Decimal | None:
    length = _positive(length_cm)
    width = _positive(width_cm)
    height = _positive(height_cm)
    if length is None or width is None or height is None:
        return None
    return _q4((length * width * height) / Decimal("6000"))


def _chargeable_weight(
    actual_weight: Decimal | None,
    volume_weight: Decimal | None,
) -> Decimal | None:
    if actual_weight is None:
        return volume_weight
    if volume_weight is None:
        return actual_weight
    return actual_weight if actual_weight >= volume_weight else volume_weight


def _positive(value: Decimal | None) -> Decimal | None:
    if value is None or value <= 0:
        return None
    return value


def _non_negative(value: Decimal | None) -> Decimal | None:
    if value is None or value < 0:
        return None
    return value


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q4(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _q2_or_none(value: Decimal | None) -> Decimal | None:
    return _q2(value) if value is not None else None


def _q4_or_none(value: Decimal | None) -> Decimal | None:
    return _q4(value) if value is not None else None


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _usd_to_cny(value: Decimal | None, exchange_rate: Decimal) -> Decimal | None:
    if value is None:
        return None
    return _q2(value * exchange_rate)
