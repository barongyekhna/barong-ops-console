from __future__ import annotations

from decimal import Decimal

from r_system_v2.ra.profit_engine import ProfitInput, calculate_us_profit


def test_ra_us_profit_uses_volume_weight_when_larger_than_actual_weight() -> None:
    result = calculate_us_profit(
        ProfitInput(
            asin="B0PROFIT01",
            sell_price_usd=Decimal("50"),
            fba_fee_usd=Decimal("5"),
            unit_price_cny=Decimal("70"),
            domestic_shipping_cny=Decimal("10"),
            actual_weight_kg=Decimal("0.5"),
            length_cm=Decimal("40"),
            width_cm=Decimal("30"),
            height_cm=Decimal("20"),
            exchange_rate_usd_cny=Decimal("7.2"),
            min_gross_margin=Decimal("0.15"),
        )
    )

    assert result.verdict == "pass"
    assert result.amazon_referral_fee_usd == Decimal("7.50")
    assert result.volume_weight_kg == Decimal("4.0000")
    assert result.chargeable_weight_kg == Decimal("4.0000")
    assert result.first_mile_freight_cny == Decimal("32.00")
    assert result.first_mile_freight_usd == Decimal("4.44")
    assert result.unit_price_usd == Decimal("9.72")
    assert result.domestic_shipping_usd == Decimal("1.39")
    assert result.gross_profit_usd == Decimal("21.95")
    assert result.gross_margin == Decimal("0.4390")


def test_ra_us_profit_uses_actual_weight_when_larger_than_volume_weight() -> None:
    result = calculate_us_profit(
        ProfitInput(
            asin="B0PROFIT02",
            sell_price_usd=Decimal("30"),
            fba_fee_usd=Decimal("4"),
            unit_price_cny=Decimal("50"),
            domestic_shipping_cny=Decimal("0"),
            actual_weight_kg=Decimal("2"),
            length_cm=Decimal("10"),
            width_cm=Decimal("10"),
            height_cm=Decimal("10"),
            exchange_rate_usd_cny=Decimal("7.2"),
            min_gross_margin=Decimal("0.15"),
        )
    )

    assert result.volume_weight_kg == Decimal("0.1667")
    assert result.chargeable_weight_kg == Decimal("2.0000")
    assert result.first_mile_freight_cny == Decimal("16.00")
    assert result.verdict == "pass"


def test_ra_us_profit_blocks_when_required_cost_fields_are_missing() -> None:
    result = calculate_us_profit(
        ProfitInput(
            asin="B0PROFIT03",
            sell_price_usd=Decimal("35"),
            fba_fee_usd=None,
            unit_price_cny=None,
            domestic_shipping_cny=None,
            actual_weight_kg=None,
            length_cm=None,
            width_cm=None,
            height_cm=None,
        )
    )

    assert result.verdict == "blocked"
    assert result.confidence == "blocked"
    assert "缺少 Keepa FBA fee。" in result.blocked_reasons
    assert "缺少 1688 产品成本。" in result.blocked_reasons
    assert "未获取 1688 国内运费提醒，暂按 0 元计入。" in result.warnings
