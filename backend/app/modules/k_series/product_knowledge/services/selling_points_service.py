"""卖点：证据快照、证据校验、错误翻译、中英富化。

从 router 剥出来的第 3 桶（2026-09-03），是 K 里最大的一块业务逻辑 ——
「图卖感觉、字卖参数」那条家规的实现处。

几件**搬运时特意没动**的事：
  · 证据语法校验(`_evidence_syntax_is_valid`)和「事实来源可信」判定
    (`_feature_source_is_trusted`)决定一条卖点能不能过审 —— 行为一字未改。
  · 英制单位配对(`_supported_measurement_pairs`)服务「面向美国买家一律英制」。
  · 错误翻译那几支有 4 个测试文件在直接引用，router 尾部 re-export 保住它们。

`SellingPointBullet` / `SellingPointsResponse` 两个 schema 也跟着搬过来了 ——
它们本来内联在 router 里，留在那边会让本模块反过来 import router，成环。
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..buyer_display import (
    buyer_display_structured_specs,
    contains_cjk,
    imperial_measurement,
)
from ..constants import MODULE_KEY
from ..evidence_guard import canonical_package_includes, package_claim_error
from ..faq_research import evidence_number_tokens, imperial_equivalent_number_tokens
from ..models import (
    KProductKnowledgeAttribute,
    KProductKnowledgeKeyword,
    KProductKnowledgeProduct,
)
from .api_support import _execute_provider_json, _structured_execution_error_detail
from .common import (
    _product_ai_warnings,
    _safe_string_list,
    _source_text_hash,
    _stable_payload_digest,
    _strict_json_messages,
)


class SellingPointBullet(BaseModel):
    id: str | None = None
    category: str
    text: str
    # 逐条中文对照(生成后由 DeepSeek 翻译填充,双语展示用,纯展示不参与证据)
    text_zh: str | None = Field(default=None, max_length=1000)
    importance_score: int | float
    evidence: str | None = Field(default=None, max_length=512)
    evidence_excerpt: str | None = Field(default=None, max_length=1000)
    evidence_snapshot: dict[str, Any] | None = None
    evidence_digest: str | None = Field(default=None, max_length=64)
    verification_status: Literal["verified", "unverified"] = "unverified"
    review_decision: Literal["candidate", "approve", "edit", "reject"] = "candidate"


class SellingPointsResponse(BaseModel):
    bullets: list[SellingPointBullet]
    seo_keywords: list[str] = Field(default_factory=list)
    market_tags: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    source: str
    marketing_copy: str | None = None
    translated_version: str | None = None
    chinese_translation: str | None = None
    target_language: str | None = None
    product_id: str | None = None
    stored_event_id: str | None = None


def _evidence_syntax_is_valid(evidence: str | None) -> bool:
    value = str(evidence or "").strip()
    return bool(
        value == "operator_fact"
        or (value.startswith("spec:") and value[5:].strip())
        or (value.startswith("verified_feature:") and value[17:].strip())
    )


def _evidence_value_text(value: Any, unit: Any = None) -> str:
    if isinstance(value, (dict, list)):
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        rendered = str(value or "").strip()
    clean_unit = str(unit or "").strip()
    if clean_unit and not re.search(
        rf"(?<![A-Za-z]){re.escape(clean_unit)}(?![A-Za-z])",
        rendered,
        re.IGNORECASE,
    ):
        return f"{rendered} {clean_unit}".strip()
    return rendered


def _structured_spec_evidence_snapshot(
    specs: Any,
    path: str,
) -> dict[str, Any] | None:
    if not isinstance(specs, dict):
        return None
    cleaned = path.strip().strip(".")
    if not cleaned:
        return None
    canonical_additional = cleaned.casefold().startswith("additional_specs.")
    if cleaned in {"schema_version", "source", "additional_specs"} or cleaned.startswith(
        "source."
    ):
        return None
    current: Any = specs
    parent: Any = None
    found = not canonical_additional
    if found:
        for segment in cleaned.split("."):
            if isinstance(current, dict) and segment in current:
                parent = current
                current = current[segment]
            else:
                found = False
                break
    if found and current not in (None, "", [], {}):
        unit = (
            current.get("unit")
            if isinstance(current, dict)
            else None
        ) or (parent.get("unit") if isinstance(parent, dict) else None)
        label_en = ""
        value_en: Any = None
        if isinstance(current, dict):
            raw_value = current.get("raw_value")
            value = current.get("value")
            if raw_value in (None, "") and value in (None, "", [], {}):
                return None
            label = str(current.get("source_label") or cleaned).strip()
            # 运营用中文录规格,英文对照就在同一条记录上。快照必须一起带走,
            # 否则下游只能看见中文,英文文案永远「找不到证据」(2026-08-03 修复)。
            label_en = str(current.get("label_en") or "").strip()
            value_en = current.get("value_en")
            value_text = _evidence_value_text(
                raw_value if raw_value not in (None, "") else value,
                unit,
            )
        else:
            label = cleaned
            value = current
            raw_value = current
            value_text = _evidence_value_text(current)
        return {
            "evidence": f"spec:{cleaned}",
            "kind": "spec",
            "path": cleaned,
            "label": label,
            "label_en": label_en,
            "value": value,
            "value_en": value_en,
            "raw_value": raw_value,
            "unit": unit,
            "value_text": value_text,
        }
    # Canonical additional-spec paths are bound only to the exact stable key.
    # The legacy short form keeps its historical key/label aliases.
    additional_lookup = cleaned
    if canonical_additional:
        additional_lookup = cleaned.split(".", 1)[1].strip().strip(".")
        if not additional_lookup:
            return None
    normalized = re.sub(
        r"[^a-z0-9]+", "_", additional_lookup.casefold()
    ).strip("_")
    for item in specs.get("additional_specs") or []:
        if not isinstance(item, dict):
            continue
        if canonical_additional:
            if str(item.get("key") or "") != additional_lookup:
                continue
        else:
            aliases = {
                str(item.get("key") or "").casefold(),
                re.sub(
                    r"[^a-z0-9]+",
                    "_",
                    str(item.get("label") or "").casefold(),
                ).strip("_"),
            }
            if (
                additional_lookup.casefold() not in aliases
                and normalized not in aliases
            ):
                continue
        raw_value = item.get("raw_value")
        value = item.get("value")
        if raw_value in (None, "") and value in (None, "", [], {}):
            return None
        value_text = _evidence_value_text(
            raw_value if raw_value not in (None, "") else value,
            item.get("unit"),
        )
        return {
            "evidence": f"spec:{cleaned}",
            "kind": "spec",
            "path": str(item.get("key") or cleaned),
            "label": str(item.get("label") or item.get("key") or cleaned),
            "label_en": str(item.get("label_en") or "").strip(),
            "value": value,
            "value_en": item.get("value_en"),
            "raw_value": raw_value,
            "unit": item.get("unit"),
            "value_text": value_text,
        }
    return None


_TRUSTED_FEATURE_SOURCE_PREFIXES = (
    "operator",
    "manual",
    "frontend",
    "supplier",
    "verified",
    "crawler_verified",
    "f_series",
    "r_series",
    "import",
    "1688",
)
_UNTRUSTED_FEATURE_SOURCE_MARKERS = (
    "ai",
    "model",
    "unverified",
    "candidate",
    "generated",
    "claude",
    "chatgpt",
    "deepseek",
)


def _feature_source_is_trusted(source: Any) -> bool:
    normalized = str(source or "").strip().casefold()
    return bool(
        normalized
        and not any(marker in normalized for marker in _UNTRUSTED_FEATURE_SOURCE_MARKERS)
        and any(
            normalized == prefix
            or normalized.startswith(f"{prefix}:")
            or normalized.startswith(f"{prefix}_")
            for prefix in _TRUSTED_FEATURE_SOURCE_PREFIXES
        )
    )


def _selling_points_evidence_payload(
    db: Session,
    product: KProductKnowledgeProduct,
) -> dict[str, Any]:
    """Claim-safe AI input: identities are separated from evidence sources."""

    verified_features: list[dict[str, Any]] = []
    for attribute in db.scalars(
        select(KProductKnowledgeAttribute)
        .where(KProductKnowledgeAttribute.product_id == product.id)
        .order_by(KProductKnowledgeAttribute.created_at.asc())
    ):
        source = str(attribute.source or "").strip().casefold()
        human_reviewed = bool(
            attribute.reviewed_by_user_id is not None and attribute.reviewed_at is not None
        )
        trusted_source = _feature_source_is_trusted(source)
        if attribute.requires_review or not (trusted_source or human_reviewed):
            continue
        value: Any = (
            attribute.attribute_value_text
            if attribute.attribute_value_text not in (None, "")
            else attribute.attribute_value_json
        )
        verified_features.append(
            {
                "id": str(attribute.id),
                "key": attribute.attribute_key,
                "value": value,
                "unit": attribute.attribute_unit,
                "source": attribute.source,
            }
        )

    approved_keywords = [
        row.keyword_text
        for row in db.scalars(
            select(KProductKnowledgeKeyword)
            .where(
                KProductKnowledgeKeyword.product_id == product.id,
                KProductKnowledgeKeyword.status == "approved",
            )
            .order_by(KProductKnowledgeKeyword.created_at.asc())
        )
    ]
    package_includes = canonical_package_includes(
        getattr(product, "package_includes_json", None),
        product.structured_specs_json,
    )
    structured_specs = dict(product.structured_specs_json or {})
    if package_includes:
        # This compatibility projection makes ``spec:package_includes`` a real,
        # resolvable evidence reference without changing the canonical K column.
        structured_specs["package_includes"] = package_includes
    return {
        "identity": {
            "product_id": str(product.id),
            "product_key": product.product_key,
            "sku": product.sku,
            "name": product.product_name_en,
            "product_type": product.product_type,
            "target_market": product.target_market,
            "target_language": product.canonical_language,
            "main_keyword": product.primary_keyword,
        },
        "structured_specs_json": structured_specs,
        "structured_specs_buyer_display": buyer_display_structured_specs(
            structured_specs,
            target_market=product.target_market or "US",
        ),
        "package_includes": package_includes,
        "verified_features": verified_features,
        "operator_facts": [product.manual_notes] if product.manual_notes else [],
        # Keywords guide wording/search intent only; the prompt explicitly
        # forbids using them as claim evidence.
        "approved_non_risk_keywords": approved_keywords,
    }


def _verified_feature_evidence_snapshot(
    db: Session,
    product: KProductKnowledgeProduct,
    feature_ref: str,
) -> tuple[dict[str, Any] | None, str | None]:
    normalized_ref = feature_ref.strip().casefold()
    attributes = list(
        db.scalars(
            select(KProductKnowledgeAttribute).where(
                KProductKnowledgeAttribute.product_id == product.id
            )
        )
    )
    for attribute in attributes:
        if normalized_ref not in {
            str(attribute.id).casefold(),
            str(attribute.attribute_key or "").casefold(),
        }:
            continue
        source = str(attribute.source or "").strip().casefold()
        human_reviewed = bool(
            attribute.reviewed_by_user_id is not None and attribute.reviewed_at is not None
        )
        trusted_source = _feature_source_is_trusted(source)
        if attribute.requires_review or not (trusted_source or human_reviewed):
            return None, (
                "Verified feature must have an explicit trusted/operator source or "
                f"completed human review: verified_feature:{feature_ref}"
            )
        raw_value: Any = (
            attribute.attribute_value_text
            if attribute.attribute_value_text not in (None, "")
            else attribute.attribute_value_json
        )
        return {
            "evidence": f"verified_feature:{feature_ref}",
            "kind": "verified_feature",
            "feature_id": str(attribute.id),
            "key": attribute.attribute_key,
            "value": raw_value,
            "unit": attribute.attribute_unit,
            "value_text": _evidence_value_text(raw_value, attribute.attribute_unit),
            "source": attribute.source,
        }, None
    return None, f"Verified feature evidence was not found: verified_feature:{feature_ref}"


def _selling_point_evidence_snapshot(
    db: Session,
    product: KProductKnowledgeProduct,
    evidence: str | None,
    *,
    operator_excerpt: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    value = str(evidence or "").strip()
    if not _evidence_syntax_is_valid(value):
        return None, "Evidence must be spec:<field>, verified_feature:<id>, or operator_fact."
    if value == "operator_fact":
        excerpt = str(operator_excerpt or "").strip()
        if not excerpt:
            return None, "operator_fact requires a concrete evidence_excerpt supplied by the operator."
        return {
            "evidence": value,
            "kind": "operator_fact",
            "value_text": excerpt,
        }, None
    if value.startswith("spec:"):
        structured_specs = dict(product.structured_specs_json or {})
        package_includes = canonical_package_includes(
            getattr(product, "package_includes_json", None),
            product.structured_specs_json,
        )
        if package_includes:
            structured_specs["package_includes"] = package_includes
        snapshot = _structured_spec_evidence_snapshot(
            structured_specs, value[5:]
        )
        if snapshot is None:
            return None, f"Structured specification evidence was not found: {value}"
        display_rows = buyer_display_structured_specs(
            structured_specs,
            target_market=product.target_market or "US",
        ).get("rows") or []
        display = next(
            (
                row
                for row in display_rows
                if isinstance(row, dict)
                and (
                    str(row.get("path") or "")
                    == str(snapshot.get("path") or "")
                    or str(row.get("path") or "").endswith(
                        "." + str(snapshot.get("path") or "")
                    )
                )
            ),
            None,
        )
        if display is not None:
            display_text = _evidence_value_text(
                display.get("display_value"), display.get("display_unit")
            )
            snapshot["source_value_text"] = snapshot.get("value_text")
            snapshot["buyer_display"] = display
            snapshot["value_text"] = display_text
        return snapshot, None
    return _verified_feature_evidence_snapshot(db, product, value.split(":", 1)[1])


def _selling_point_evidence_error(
    db: Session,
    product: KProductKnowledgeProduct,
    evidence: str | None,
) -> str | None:
    # Syntax/existence helper retained for read-only status projection. The
    # approval endpoint additionally validates the exact snapshot and claim.
    if str(evidence or "").strip() == "operator_fact":
        return None
    _, error = _selling_point_evidence_snapshot(db, product, evidence)
    return error


# IPX0-8 / IP65 / IP67 / IP68 …… 枚举写不全,一律走正则(旧表只有 ip65/ip67,
# IPX8 这种铁证反而被判「不支持防水」)。
_IP_RATING_PATTERN = re.compile(r"\bip(?:x\d|\d[x\d])\b")
# CE / RoHS / UL 这类认证与 IP 防护等级,本身就是「安全」主题的证据。
_SAFETY_EVIDENCE_PATTERN = re.compile(
    r"\b(?:ce|rohs|ul|etl|fcc|un38\s?3|ipx?\d)\b|认证|防水等级|安规|3c"
)

# 证据的 label 常是运营录入的中文,卖点是英文写的 —— 词表必须双语,
# 否则「续航」撑不起 runtime、「防水等级」撑不起 waterproof。
# 每一项可以是字面词,也可以是正则(正则直接在归一化文本上匹配)。
_EVIDENCE_TOPIC_TERMS: tuple[tuple[str, tuple[Any, ...]], ...] = (
    (
        "wind",
        ("wind", "windproof", "wind-resistant", "wind resistant", "防风", "抗风"),
    ),
    (
        "water",
        (
            "waterproof",
            "water-resistant",
            "water resistant",
            # 不收 "submersible":那是泵的类型(潜水泵),不是防水声称,
            # 收了会把「Submersible pump draws water from…」这种句子误杀。
            "防水",
            "防泼水",
            "浸没",
            "潜水",
            _IP_RATING_PATTERN,
        ),
    ),
    ("indoor", ("indoor", "indoors", "home use", "室内", "家用")),
    ("safety", ("safe", "safety", "hazard-free", "安全", "安规")),
    (
        "runtime",
        (
            "runtime",
            "run time",
            "battery life",
            "hours",
            "hour",
            "续航",
            "工作时间",
            "使用时间",
            "运行时间",
        ),
    ),
    ("ignition", ("ignition", "ignite", "piezo", "lighter-free", "点火")),
    ("weight", ("lightweight", "weight", "weighs", "lb", "kg", "重量", "净重")),
    (
        "size",
        (
            "compact",
            "dimensions",
            "dimension",
            "folded",
            "inch",
            "cm",
            "尺寸",
            "规格",
            "折叠",
        ),
    ),
    (
        "material",
        ("material", "steel", "aluminum", "aluminium", "abs", "材质", "材料"),
    ),
    (
        "certification",
        ("certified", "certification", "ce", "rohs", "ul", "认证"),
    ),
)

_MEASUREMENT_NUMBER_PATTERN = (
    r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+"
)
_CLAIM_MEASUREMENT_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9.,])(?P<number>{_MEASUREMENT_NUMBER_PATTERN})\s*"
    r"(?P<unit>millimeters?|millimetres?|centimeters?|centimetres?|"
    r"kilograms?|grams?|milliliters?|millilitres?|liters?|litres?|"
    r"inches?|quarts?|ounces?|pounds?|mm|cm|kg|ml|qt|oz|lb|in|g|l)\b",
    flags=re.IGNORECASE,
)

_MEASUREMENT_UNIT_ALIASES = {
    "millimeter": "mm",
    "millimeters": "mm",
    "millimetre": "mm",
    "millimetres": "mm",
    "centimeter": "cm",
    "centimeters": "cm",
    "centimetre": "cm",
    "centimetres": "cm",
    "kilogram": "kg",
    "kilograms": "kg",
    "gram": "g",
    "grams": "g",
    "milliliter": "ml",
    "milliliters": "ml",
    "millilitre": "ml",
    "millilitres": "ml",
    "liter": "l",
    "liters": "l",
    "litre": "l",
    "litres": "l",
    "inch": "in",
    "inches": "in",
    "quart": "qt",
    "quarts": "qt",
    "ounce": "oz",
    "ounces": "oz",
    "pound": "lb",
    "pounds": "lb",
}
_CONVERTIBLE_MEASUREMENT_UNITS = frozenset({"mm", "cm", "kg", "g", "ml", "l"})
_MEASUREMENT_UNIT_DIMENSIONS = {
    "mm": "length",
    "cm": "length",
    "in": "length",
    "kg": "mass",
    "g": "mass",
    "lb": "mass",
    "oz": "mass",
    "ml": "volume",
    "l": "volume",
    "qt": "volume",
}


def _canonical_measurement_unit(value: Any) -> str:
    cleaned = str(value or "").strip().casefold()
    return _MEASUREMENT_UNIT_ALIASES.get(cleaned, cleaned)


def _measurement_pairs(value: Any) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for match in _CLAIM_MEASUREMENT_PATTERN.finditer(str(value or "")):
        numbers = evidence_number_tokens(match.group("number"))
        if not numbers:
            continue
        pairs.add(
            (
                next(iter(numbers)),
                _canonical_measurement_unit(match.group("unit")),
            )
        )
    return pairs


_STRUCTURED_MEASUREMENT_KEYS = frozenset(
    {
        "value",
        "width",
        "height",
        "length",
        "depth",
        "diameter",
        "thickness",
        "capacity",
    }
)


def _structured_measurement_pairs(
    value: Any,
    *,
    default_unit: Any = None,
) -> set[tuple[str, str]]:
    """结构化数值里的「数字+单位」配对。

    verified_feature 的重量/尺寸存成嵌套字典
    (``{"unit": "lb", "value": 2.67, "source": {"unit": "g", "value": 1211}}``),
    只靠正则扫 JSON 文本永远配不出「2.67 lb」—— 凡是带单位的重量/尺寸卖点
    都会被判「证据里没有这个数字+单位」(2026-08-03 修复)。
    每个数字只跟它所在那一层声明的单位绑定,不放宽门禁。
    """

    pairs: set[tuple[str, str]] = set()
    if isinstance(value, list):
        for item in value:
            pairs.update(
                _structured_measurement_pairs(item, default_unit=default_unit)
            )
        return pairs
    if not isinstance(value, dict):
        return pairs
    local_unit = _canonical_measurement_unit(value.get("unit") or default_unit)
    for key, item in value.items():
        if isinstance(item, (dict, list)):
            pairs.update(_structured_measurement_pairs(item, default_unit=local_unit))
            continue
        if key not in _STRUCTURED_MEASUREMENT_KEYS:
            continue
        if isinstance(item, bool) or not isinstance(item, (int, float, str)):
            continue
        if local_unit not in _MEASUREMENT_UNIT_DIMENSIONS:
            continue
        pairs.update(
            (number, local_unit) for number in evidence_number_tokens(item)
        )
    return pairs


def _supported_measurement_pairs(snapshot: dict[str, Any]) -> set[tuple[str, str]]:
    """Bind factual and buyer-display numbers to their verified units."""

    explicit_pairs: set[tuple[str, str]] = set()
    for key in ("value", "raw_value", "value_text"):
        explicit_pairs.update(_measurement_pairs(snapshot.get(key)))
    for key in ("value", "raw_value"):
        explicit_pairs.update(
            _structured_measurement_pairs(
                snapshot.get(key), default_unit=snapshot.get("unit")
            )
        )

    source_unit = _canonical_measurement_unit(snapshot.get("unit"))
    if source_unit not in _CONVERTIBLE_MEASUREMENT_UNITS:
        pairs = set(explicit_pairs)
        for number, explicit_unit in explicit_pairs:
            if explicit_unit not in _CONVERTIBLE_MEASUREMENT_UNITS:
                continue
            converted = imperial_measurement(number, explicit_unit)
            if converted is None:
                continue
            rendered, converted_unit = converted
            pairs.update(
                (converted_number, converted_unit)
                for converted_number in evidence_number_tokens(rendered)
            )
        return pairs

    metric_value = snapshot.get("value")
    if metric_value in (None, "", [], {}):
        metric_value = snapshot.get("raw_value")

    pairs = {
        (number, source_unit)
        for number in evidence_number_tokens(metric_value)
    }
    source_dimension = _MEASUREMENT_UNIT_DIMENSIONS[source_unit]
    pairs.update(
        pair
        for pair in explicit_pairs
        if _MEASUREMENT_UNIT_DIMENSIONS.get(pair[1]) == source_dimension
    )

    converted = imperial_measurement(metric_value, source_unit)
    if converted is not None:
        rendered, converted_unit = converted
        pairs.update(
            (number, converted_unit)
            for number in evidence_number_tokens(rendered)
        )
    else:
        for number in evidence_number_tokens(metric_value):
            scalar = imperial_measurement(number, source_unit)
            if scalar is None:
                continue
            rendered, converted_unit = scalar
            pairs.update(
                (converted_number, converted_unit)
                for converted_number in evidence_number_tokens(rendered)
            )
    return pairs


def _normalized_evidence_text(value: Any) -> str:
    # 保留中文:运营者证据摘录常直接摘自中文原始描述(2026-07-22 修复:
    # 原来只留 ASCII,中文摘录被洗成空串,operator_fact 全军覆没)。
    return re.sub(r"[^a-z0-9一-鿿]+", " ", str(value or "").casefold()).strip()


def _contains_evidence_phrase(haystack: str, phrase: Any) -> bool:
    # 正则项(如 IP 防护等级)直接在归一化文本上匹配。
    if isinstance(phrase, re.Pattern):
        return bool(phrase.search(haystack))
    needle = _normalized_evidence_text(phrase)
    if not needle:
        return False
    # 中文不分词,词边界永远匹配不上(「防水等级」里找不到「防水」),按子串比。
    if contains_cjk(needle):
        return needle in haystack
    return bool(re.search(rf"(?:^|\s){re.escape(needle)}(?:$|\s)", haystack))


def _enrich_selling_points_chinese(
    db: Session,
    *,
    context: Any,
    response: "SellingPointsResponse",
) -> "SellingPointsResponse":
    """生成后的中文兜底翻译:逐条卖点 text_zh + 整体 chinese_translation。

    已经带中文的字段不重翻;全部齐整则零调用直接返回。
    """

    needs_bullets = any(
        not str(bullet.text_zh or "").strip() for bullet in response.bullets
    )
    needs_blob = not str(response.chinese_translation or "").strip()
    if not response.bullets or (not needs_bullets and not needs_blob):
        return response

    payload: dict[str, Any] = {
        "task": "selling_points_translation",
        "bullets": [bullet.text for bullet in response.bullets],
        "marketing_copy": response.marketing_copy
        or response.translated_version
        or "",
    }
    payload["messages"] = _strict_json_messages(
        instruction=(
            "You are a bilingual ecommerce copywriter. Translate the given "
            "English selling-point bullets into Simplified Chinese one by one, "
            "faithful and natural for a Chinese seller reviewing them. Return "
            'STRICT JSON: {"bullets_zh": ["...", ...], "chinese_translation": '
            '"..."}. bullets_zh must contain exactly one Chinese line per input '
            "bullet, in order. chinese_translation is a Chinese version of the "
            "marketing copy (or a concise Chinese summary of the bullets when "
            "no copy is given)."
        ),
        payload=payload,
    )
    # 出网前结束事务,避免 idle-in-transaction 超时(与主生成调用同款姿势)
    db.rollback()
    out = _execute_provider_json(
        db,
        context=context,
        provider="deepseek",
        task_type="selling_points_translation",
        payload=payload,
    )
    raw_zh = out.get("bullets_zh")
    bullets_zh = raw_zh if isinstance(raw_zh, list) else []
    new_bullets = []
    for index, bullet in enumerate(response.bullets):
        zh = (
            str(bullets_zh[index]).strip()
            if index < len(bullets_zh) and isinstance(bullets_zh[index], str)
            else ""
        )
        if zh and not str(bullet.text_zh or "").strip():
            new_bullets.append(bullet.model_copy(update={"text_zh": zh}))
        else:
            new_bullets.append(bullet)
    blob = out.get("chinese_translation")
    chinese_translation = response.chinese_translation
    if not str(chinese_translation or "").strip() and isinstance(blob, str):
        chinese_translation = blob.strip() or chinese_translation
    return response.model_copy(
        update={"bullets": new_bullets, "chinese_translation": chinese_translation}
    )


def _selling_point_support_error(
    bullet: SellingPointBullet,
    snapshot: dict[str, Any],
    *,
    package_includes: Any = None,
    structured_specs: dict[str, Any] | None = None,
) -> str | None:
    claim = _normalized_evidence_text(bullet.text)
    # 中文 label 与英文对照(label_en/value_en/买家展示行)一起进证据文本,
    # 中文规格才撑得住英文卖点。
    buyer_display = snapshot.get("buyer_display")
    if not isinstance(buyer_display, dict):
        buyer_display = {}
    fact = _normalized_evidence_text(
        " ".join(
            str(source.get(key) or "")
            for source, keys in (
                (snapshot, ("path", "label", "label_en", "key", "value_text", "value_en")),
                (buyer_display, ("label", "display_value", "display_unit")),
            )
            for key in keys
        )
    )
    operator_bridge = (
        _normalized_evidence_text(bullet.evidence_excerpt)
        if snapshot.get("kind") == "operator_fact"
        else ""
    )
    support = f"{fact} {operator_bridge}".strip()

    claim_numbers = evidence_number_tokens(bullet.text)
    support_numbers = evidence_number_tokens(
        " ".join(
            str(snapshot.get(key) or "")
            for key in (
                "path",
                "label",
                "key",
                "value_text",
                "value",
                "raw_value",
            )
        )
    )
    metric_value = snapshot.get("value")
    if metric_value in (None, "", [], {}):
        metric_value = snapshot.get("raw_value")
    support_numbers.update(
        imperial_equivalent_number_tokens(metric_value, snapshot.get("unit"))
    )
    claimed_measurements = _measurement_pairs(bullet.text)
    supported_measurements = _supported_measurement_pairs(snapshot)
    support_numbers.update(number for number, _unit in supported_measurements)
    package_items = canonical_package_includes(package_includes, structured_specs)
    if re.search(r"\b\d+\s*(?:-|\s)?\s*(?:piece|pieces|pc|pcs)\b", claim):
        support_numbers.add(str(len(package_items)))
    unsupported_numbers = sorted(claim_numbers - support_numbers)
    if unsupported_numbers:
        return "Claim contains numbers absent from the current evidence: " + ", ".join(unsupported_numbers)

    unsupported_measurements = sorted(claimed_measurements - supported_measurements)
    if unsupported_measurements:
        rendered = ", ".join(
            f"{number} {unit}" for number, unit in unsupported_measurements
        )
        return (
            "Claim contains number/unit pairs absent from the current evidence: "
            + rendered
        )

    # 英文主题词匹配只适用于结构化证据(spec/verified_feature)。
    # operator_fact 的摘录多为中文原文,人工逐条批准本身即是背书,
    # 强行用英文词表比对必然误杀(2026-07-22 修复)。
    if snapshot.get("kind") != "operator_fact":
        for topic, terms in _EVIDENCE_TOPIC_TERMS:
            claim_has_topic = any(
                _contains_evidence_phrase(claim, term) for term in terms
            )
            if not claim_has_topic:
                continue
            if any(_contains_evidence_phrase(support, term) for term in terms):
                continue
            # 防护等级与认证(IPX8 / CE / RoHS / UL)本身就是安全证据,
            # 不必在证据文本里再出现「安全」二字(用户 2026-08-03 拍板)。
            if topic == "safety" and _SAFETY_EVIDENCE_PATTERN.search(support):
                continue
            return f"Evidence does not support the claim topic '{topic}'."

    if snapshot.get("kind") == "operator_fact" and not operator_bridge:
        return "operator_fact requires a concrete evidence_excerpt."
    package_error = package_claim_error(
        bullet.text,
        package_includes=package_includes,
        structured_specs=structured_specs,
    )
    if package_error:
        return package_error
    return None


_EVIDENCE_TOPIC_LABELS_ZH = {
    "wind": "防风",
    "water": "防水",
    "indoor": "室内使用",
    "safety": "安全",
    "runtime": "续航",
    "ignition": "点火",
    "weight": "重量",
    "size": "尺寸",
    "material": "材质",
    "certification": "认证",
}


def _humanize_selling_point_error(error: str) -> str:
    """把门禁的英文判词翻成运营看得懂、能照着改的中文。

    判词本体保持英文不动(既有测试逐字断言),中文化只发生在返回给人看的这一层。
    """

    value = str(error or "").strip()
    topic = re.match(r"Evidence does not support the claim topic '(.+)'\.$", value)
    if topic:
        name = _EVIDENCE_TOPIC_LABELS_ZH.get(topic.group(1), topic.group(1))
        return (
            f"文案里说了「{name}」,但绑的这条证据跟{name}无关。"
            f"请改绑一条能证明{name}的规格,或把{name}的说法从文案里去掉。"
        )
    numbers = re.match(
        r"Claim contains numbers absent from the current evidence: (.+)$", value
    )
    if numbers:
        return f"文案里的数字 {numbers.group(1)} 在这条证据里找不到,请改数字或换证据。"
    pairs = re.match(
        r"Claim contains number/unit pairs absent from the current evidence: (.+)$",
        value,
    )
    if pairs:
        return (
            f"文案里的「{pairs.group(1)}」在这条证据里找不到(数字或单位对不上),"
            "请改文案或换证据。"
        )
    if value == "operator_fact requires a concrete evidence_excerpt.":
        return "选了「运营自证」就必须填一段具体的证据摘录(工厂原话/资料原文)。"
    missing_spec = re.match(
        r"Structured specification evidence was not found: (.+)$", value
    )
    if missing_spec:
        return f"找不到这条规格字段:{missing_spec.group(1)},请重新选一条证据。"
    missing_feature = re.match(
        r"Verified feature evidence was not found: (.+)$", value
    )
    if missing_feature:
        return f"找不到这条已验证属性:{missing_feature.group(1)},请重新选一条证据。"
    if value.startswith("Evidence must be spec:"):
        return (
            "证据格式不对,只能填 spec:<规格字段>、verified_feature:<属性 ID> "
            "或 operator_fact。"
        )
    if value == "Every candidate must be approved, edited, or rejected.":
        return "这条还没做决定,请选通过 / 编辑后通过 / 拒绝。"
    duplicate = re.match(r"Duplicate selling-point id: (.+)$", value)
    if duplicate:
        return f"卖点 id 重复了:{duplicate.group(1)}。"
    components = re.match(r"Unsupported package component\(s\): (.+)$", value)
    if components:
        return (
            f"文案提到了配件 {components.group(1)},但包装清单里没有,"
            "请补进包装清单或从文案里去掉。"
        )
    piece = re.match(r"(\d+)-piece claim requires a verified piece_count\.$", value)
    if piece:
        return f"写了「{piece.group(1)} 件套」,但包装清单没有可核对的件数。"
    mismatch = re.match(
        r"(\d+)-piece claim does not match verified piece count \((\d+)\)\.$", value
    )
    if mismatch:
        return (
            f"写了「{mismatch.group(1)} 件套」,但包装清单实际是 "
            f"{mismatch.group(2)} 件。"
        )
    return value


def _selling_point_review_error_message(
    review_errors: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> str:
    """一次把问题说全 —— 只报第一条会让人反复提交反复撞墙。"""

    lines = [f"卖点证据审批未通过(共 {len(review_errors)} 条问题):"]
    for item in review_errors[:limit]:
        text = str(item.get("text") or "").strip()
        if len(text) > 40:
            text = text[:40] + "…"
        head = f"第 {int(item.get('index', 0)) + 1} 条"
        if text:
            head = f"{head}「{text}」"
        lines.append(f"{head}:{_humanize_selling_point_error(str(item.get('error')))}")
    if len(review_errors) > limit:
        lines.append(f"另有 {len(review_errors) - limit} 条问题未列出。")
    return "\n".join(lines)


def _mark_selling_point_evidence_status(
    db: Session,
    product: KProductKnowledgeProduct,
    response: SellingPointsResponse,
) -> SellingPointsResponse:
    bullets = []
    for bullet in response.bullets:
        snapshot, error = _selling_point_evidence_snapshot(
            db,
            product,
            bullet.evidence,
            operator_excerpt=bullet.evidence_excerpt,
        )
        support_error = (
            _selling_point_support_error(
                bullet,
                snapshot,
                package_includes=getattr(product, "package_includes_json", None),
                structured_specs=product.structured_specs_json,
            )
            if snapshot is not None
            else None
        )
        # ``operator_fact`` becomes verified only when the operator explicitly
        # approves/edits the row at the manual gate below.
        operator_attestation_pending = bullet.evidence == "operator_fact"
        bullets.append(
            bullet.model_copy(
                update={
                    "verification_status": (
                        "unverified"
                        if error or support_error or operator_attestation_pending
                        else "verified"
                    )
                }
            )
        )
    return response.model_copy(update={"bullets": bullets})


def _normalize_selling_points_response(
    provider_output: dict[str, Any],
    *,
    product: KProductKnowledgeProduct | None = None,
    source: str,
    stored_event_id: UUID | None = None,
) -> SellingPointsResponse:
    def _first_present_from(record: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = record.get(key)
            if value:
                return value
        return None

    def _first_present(*keys: str) -> Any:
        return _first_present_from(provider_output, *keys)

    raw_bullets = _first_present(
        "bullets",
        "selling_points",
        "high_conversion_selling_points",
        "structured_bullet_points",
        "bullet_points",
        "conversion_selling_points",
        "conversion_bullets",
        "value_propositions",
        "卖点",
        "转化卖点",
    ) or []
    if isinstance(raw_bullets, dict):
        raw_bullets = _first_present_from(
            raw_bullets,
            "items",
            "bullets",
            "points",
            "selling_points",
            "structured_bullet_points",
        ) or list(raw_bullets.values())
    bullets: list[SellingPointBullet] = []
    if isinstance(raw_bullets, list):
        for index, raw in enumerate(raw_bullets, start=1):
            if isinstance(raw, dict):
                text = str(
                    raw.get("text")
                    or raw.get("copy")
                    or raw.get("point")
                    or raw.get("headline")
                    or raw.get("benefit")
                    or raw.get("value_proposition")
                    or raw.get("卖点")
                    or raw.get("文案")
                    or ""
                ).strip()
                category = str(
                    raw.get("category")
                    or raw.get("type")
                    or raw.get("theme")
                    or raw.get("类别")
                    or "conversion"
                ).strip()
                score_raw = (
                    raw.get("importance_score")
                    or raw.get("score")
                    or raw.get("priority")
                    or raw.get("权重")
                    or 1
                )
                evidence = str(raw.get("evidence") or "").strip() or None
                evidence_excerpt = (
                    str(raw.get("evidence_excerpt") or raw.get("proof") or "").strip()
                    or None
                )
            else:
                text = str(raw).strip()
                category = "conversion"
                score_raw = index
                evidence = None
                evidence_excerpt = None
            if not text:
                continue
            try:
                score = float(score_raw)
            except (TypeError, ValueError):
                score = float(index)
            bullets.append(
                SellingPointBullet(
                    id=(
                        str(raw.get("id")).strip()
                        if isinstance(raw, dict) and raw.get("id")
                        else f"sp-{index}"
                    ),
                    category=category or "conversion",
                    text=text,
                    importance_score=score,
                    evidence=evidence,
                    evidence_excerpt=evidence_excerpt,
                    # Provider claims are candidates. Syntax is not proof and
                    # only the product-aware/manual gate may mark them verified.
                    verification_status="unverified",
                )
            )
    if not bullets and isinstance(provider_output.get("content"), str):
        bullets.append(
            SellingPointBullet(
                category="marketing",
                text=str(provider_output["content"]).strip(),
                importance_score=1,
                verification_status="unverified",
            )
        )
    if not bullets:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_structured_execution_error_detail(
                reason="provider_error",
                code="SELLING_POINTS_EMPTY",
                message="DeepSeek selling points response did not include usable bullet points.",
                module_id=MODULE_KEY,
            ),
        )

    confidence_raw = provider_output.get("confidence_score") or provider_output.get("confidence") or 0.8
    try:
        confidence = max(0.0, min(1.0, float(confidence_raw)))
    except (TypeError, ValueError):
        confidence = 0.8
    return SellingPointsResponse(
        bullets=bullets,
        seo_keywords=_safe_string_list(
            _first_present("seo_keywords", "keywords", "search_keywords", "关键词")
        ),
        market_tags=_safe_string_list(
            _first_present("market_tags", "tags", "audience_tags", "市场标签")
        ),
        confidence_score=confidence,
        source=source,
        marketing_copy=(
            _first_present("marketing_copy", "copy", "conversion_copy", "营销文案")
            if isinstance(
                _first_present("marketing_copy", "copy", "conversion_copy", "营销文案"),
                str,
            )
            else None
        ),
        translated_version=(
            _first_present("translated_version", "localized_copy", "translation")
            if isinstance(
                _first_present("translated_version", "localized_copy", "translation"),
                str,
            )
            else None
        ),
        chinese_translation=(
            _first_present(
                "chinese_translation",
                "zh_translation",
                "translated_version_zh",
                "chinese_version",
                "中文翻译",
                "中文版本",
            )
            if isinstance(
                _first_present(
                    "chinese_translation",
                    "zh_translation",
                    "translated_version_zh",
                    "chinese_version",
                    "中文翻译",
                    "中文版本",
                ),
                str,
            )
            else None
        ),
        target_language=(
            str(provider_output.get("target_language"))
            if provider_output.get("target_language")
            else product.canonical_language if product else None
        ),
        product_id=str(product.id) if product else None,
        stored_event_id=str(stored_event_id) if stored_event_id else None,
    )


def _stored_selling_points_payload(
    product: KProductKnowledgeProduct,
    *,
    approved_only: bool = False,
) -> dict[str, Any] | None:
    approved = product.selling_points_approved_json
    if isinstance(approved, dict):
        return approved
    if approved_only:
        return None
    candidates = product.selling_points_candidates_json
    if isinstance(candidates, dict):
        return candidates
    # Read-only compatibility for records written before the evidence columns.
    payload = _product_ai_warnings(product).get("selling_points")
    return payload if isinstance(payload, dict) else None


def _selling_points_snapshot(product: KProductKnowledgeProduct) -> dict[str, Any]:
    payload = _stored_selling_points_payload(product, approved_only=True)
    if payload is None:
        empty = {"count": 0, "payload": None}
        return {**empty, "digest": _stable_payload_digest(empty)}
    bullets = payload.get("bullets")
    count = len(bullets) if isinstance(bullets, list) else 0
    stable_payload = {
        "bullets": bullets if isinstance(bullets, list) else [],
        "chinese_translation": payload.get("chinese_translation"),
        "confidence_score": payload.get("confidence_score"),
        "market_tags": _safe_string_list(payload.get("market_tags")),
        "marketing_copy": payload.get("marketing_copy"),
        "product_id": str(product.id),
        "seo_keywords": _safe_string_list(payload.get("seo_keywords")),
        "source": payload.get("source"),
        "target_language": payload.get("target_language"),
        "translated_version": payload.get("translated_version"),
        "review_status": payload.get("review_status"),
    }
    snapshot_payload = {"count": count, "payload": stable_payload}
    return {
        **snapshot_payload,
        "digest": _stable_payload_digest(snapshot_payload),
    }


def _selling_points_response_from_payload(
    product: KProductKnowledgeProduct,
    payload: dict[str, Any],
) -> SellingPointsResponse:
    return SellingPointsResponse(
        bullets=[
            SellingPointBullet.model_validate(bullet)
            for bullet in payload.get("bullets", [])
            if isinstance(bullet, dict)
        ],
        seo_keywords=_safe_string_list(payload.get("seo_keywords")),
        market_tags=_safe_string_list(payload.get("market_tags")),
        confidence_score=float(payload.get("confidence_score") or 1),
        source=str(payload.get("source") or "manual_review"),
        marketing_copy=(
            str(payload["marketing_copy"])
            if isinstance(payload.get("marketing_copy"), str)
            else None
        ),
        translated_version=(
            str(payload["translated_version"])
            if isinstance(payload.get("translated_version"), str)
            else None
        ),
        chinese_translation=(
            str(payload["chinese_translation"])
            if isinstance(payload.get("chinese_translation"), str)
            else None
        ),
        target_language=(
            str(payload["target_language"])
            if isinstance(payload.get("target_language"), str)
            else product.canonical_language
        ),
        product_id=str(product.id),
    )
