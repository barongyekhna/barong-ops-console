"""Deterministic shipping-class assignment engine.

The engine only evaluates registered rules.  It does not infer, guess, or call
external services.  Missing weight data therefore fails closed unless an
explicit US-stock or battery override matches first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


MISSING_WEIGHT_REASON = "重量数据缺失，无法确定性分配"
NO_MATCH_REASON = "没有命中任何规则"

_KG_PER_LB = Decimal("0.4536")
_CM_PER_INCH = Decimal("2.54")
_VOLUMETRIC_DIVISOR = Decimal("6000")
_BOUNDARY_RATIO = Decimal("0.10")


@dataclass(frozen=True)
class ShippingDecision:
    """Pure evaluation result plus the trace persisted on a K product."""

    shipping_class_slug: str | None
    rule_id: str | None
    rule_type: str | None
    weight_kg: float | None
    volumetric_kg: float | None
    used_kg: float | None
    review_needed: bool
    review_reason: str | None
    matched_at: str
    skipped_manual: bool = False

    def assignment_json(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "matched_at": self.matched_at,
            "weight_kg": self.weight_kg,
            "volumetric_kg": self.volumetric_kg,
            "used_kg": self.used_kg,
            "review_reason": self.review_reason,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


def _as_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def parse_weight_kg(value: Any) -> float | None:
    """Parse a supported weight JSON value and return kilograms."""

    parsed = _parse_weight_decimal(value)
    return _as_float(parsed)


def _parse_weight_decimal(value: Any) -> Decimal | None:
    if isinstance(value, dict):
        amount = _decimal(value.get("value"))
        unit_value = value.get("unit")
        if amount is None or not isinstance(unit_value, str):
            return None
        unit = unit_value.strip().lower()
        if unit in {"kg", "千克"}:
            return amount
        if unit in {"g", "克"}:
            return amount / Decimal("1000")
        if unit in {"lb", "磅"}:
            return amount * _KG_PER_LB
        return None
    return _decimal(value)


def product_weight_kg(product: Any) -> float | None:
    """Parse package weight first and fall back to the product weight."""

    parsed = _product_weight_decimal(product)
    return _as_float(parsed)


def _product_weight_decimal(product: Any) -> Decimal | None:
    package_weight = _parse_weight_decimal(
        getattr(product, "package_weight_json", None)
    )
    if package_weight is not None:
        return package_weight
    return _parse_weight_decimal(getattr(product, "weight_json", None))


def parse_volumetric_weight_kg(value: Any) -> float | None:
    """Parse package dimensions and calculate L*W*H(cm)/6000."""

    parsed = _parse_volumetric_decimal(value)
    return _as_float(parsed)


def _parse_volumetric_decimal(value: Any) -> Decimal | None:
    if not isinstance(value, dict):
        return None
    length = _decimal(value.get("length"))
    width = _decimal(value.get("width"))
    height = _decimal(value.get("height"))
    unit_value = value.get("unit")
    if (
        length is None
        or width is None
        or height is None
        or not isinstance(unit_value, str)
    ):
        return None
    unit = unit_value.strip().lower()
    if unit == "in":
        length *= _CM_PER_INCH
        width *= _CM_PER_INCH
        height *= _CM_PER_INCH
    elif unit != "cm":
        return None
    return length * width * height / _VOLUMETRIC_DIVISOR


def product_billing_weights(
    product: Any,
) -> tuple[float | None, float | None, float | None]:
    """Return actual, volumetric, and billable kilograms for a product."""

    weight, volumetric, used = _product_billing_decimals(product)
    return _as_float(weight), _as_float(volumetric), _as_float(used)


def _product_billing_decimals(
    product: Any,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    weight = _product_weight_decimal(product)
    volumetric = _parse_volumetric_decimal(
        getattr(product, "package_dimensions_json", None)
    )
    used = _max_available(weight, volumetric)
    return weight, volumetric, used


def _max_available(
    first: Decimal | None,
    second: Decimal | None,
) -> Decimal | None:
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def _format_kg(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _near_weight_band_boundary(
    used_kg: Decimal,
    min_weight_kg: Decimal | None,
    max_weight_kg: Decimal | None,
) -> bool:
    for boundary in (min_weight_kg, max_weight_kg):
        if boundary is None:
            continue
        tolerance = abs(boundary) * _BOUNDARY_RATIO
        if abs(used_kg - boundary) <= tolerance:
            return True
    return False


def _decision(
    *,
    shipping_class_slug: str | None,
    rule_id: str | None,
    rule_type: str | None,
    weight_kg: Decimal | None,
    volumetric_kg: Decimal | None,
    used_kg: Decimal | None,
    review_needed: bool,
    review_reason: str | None,
    matched_at: str | None = None,
    skipped_manual: bool = False,
) -> ShippingDecision:
    return ShippingDecision(
        shipping_class_slug=shipping_class_slug,
        rule_id=rule_id,
        rule_type=rule_type,
        weight_kg=_as_float(weight_kg),
        volumetric_kg=_as_float(volumetric_kg),
        used_kg=_as_float(used_kg),
        review_needed=review_needed,
        review_reason=review_reason,
        matched_at=matched_at or _now_iso(),
        skipped_manual=skipped_manual,
    )


def evaluate_rules(
    rules: Iterable[Any],
    *,
    weight_kg: float | Decimal | int | None,
    volumetric_kg: float | Decimal | int | None,
    contains_battery: bool,
    us_stock: bool,
) -> ShippingDecision:
    """Evaluate active rules in priority order and short-circuit on first match."""

    weight = _decimal(weight_kg)
    volumetric = _decimal(volumetric_kg)
    used = _max_available(weight, volumetric)
    ordered_rules = sorted(
        (rule for rule in rules if bool(getattr(rule, "active", False))),
        key=lambda rule: (
            int(getattr(rule, "priority", 0)),
            str(getattr(rule, "id", "")),
        ),
    )

    for rule in ordered_rules:
        rule_type = str(getattr(rule, "rule_type", "") or "")
        matches = False
        minimum: Decimal | None = None
        maximum: Decimal | None = None
        if rule_type == "us_stock_override":
            matches = bool(us_stock)
        elif rule_type == "battery_override":
            matches = bool(contains_battery)
        elif rule_type == "weight_band" and used is not None:
            minimum = _decimal(getattr(rule, "min_weight_kg", None))
            maximum = _decimal(getattr(rule, "max_weight_kg", None))
            lower_matches = used >= (minimum if minimum is not None else Decimal(0))
            upper_matches = maximum is None or used < maximum
            matches = lower_matches and upper_matches
        if not matches:
            continue

        review_needed = False
        review_reason = None
        if rule_type == "weight_band" and used is not None:
            review_needed = _near_weight_band_boundary(used, minimum, maximum)
            if review_needed:
                review_reason = (
                    f"计费重 {_format_kg(used)}kg 接近段位边界，请人工复核"
                )
        return _decision(
            shipping_class_slug=str(getattr(rule, "shipping_class_slug")),
            rule_id=str(getattr(rule, "id")),
            rule_type=rule_type,
            weight_kg=weight,
            volumetric_kg=volumetric,
            used_kg=used,
            review_needed=review_needed,
            review_reason=review_reason,
        )

    reason = MISSING_WEIGHT_REASON if used is None else NO_MATCH_REASON
    return _decision(
        shipping_class_slug=None,
        rule_id=None,
        rule_type=None,
        weight_kg=weight,
        volumetric_kg=volumetric,
        used_kg=used,
        review_needed=True,
        review_reason=reason,
    )


def evaluate_product(rules: Iterable[Any], product: Any) -> ShippingDecision:
    """Parse a K product's shipping inputs, then evaluate the rule table."""

    weight, volumetric, _used = _product_billing_decimals(product)
    return evaluate_rules(
        rules,
        weight_kg=weight,
        volumetric_kg=volumetric,
        contains_battery=bool(getattr(product, "contains_battery", False)),
        us_stock=bool(getattr(product, "us_stock", False)),
    )


def assign_product(
    product: Any,
    rules: Iterable[Any],
    *,
    force: bool = False,
) -> ShippingDecision:
    """Apply a deterministic decision to one product unless it is manual."""

    existing = getattr(product, "shipping_assignment_json", None)
    if (
        not force
        and isinstance(existing, dict)
        and existing.get("rule_type") == "manual"
    ):
        weight, volumetric, used = _product_billing_decimals(product)
        return _decision(
            shipping_class_slug=getattr(product, "shipping_class", None),
            rule_id=(str(existing.get("rule_id")) if existing.get("rule_id") else None),
            rule_type="manual",
            weight_kg=weight,
            volumetric_kg=volumetric,
            used_kg=used,
            review_needed=bool(
                getattr(product, "shipping_review_needed", False)
            ),
            review_reason=(
                str(existing.get("review_reason"))
                if existing.get("review_reason") is not None
                else None
            ),
            matched_at=(
                str(existing.get("matched_at"))
                if existing.get("matched_at")
                else None
            ),
            skipped_manual=True,
        )

    decision = evaluate_product(rules, product)
    product.shipping_class = decision.shipping_class_slug
    product.shipping_assignment_json = decision.assignment_json()
    product.shipping_review_needed = decision.review_needed
    return decision
