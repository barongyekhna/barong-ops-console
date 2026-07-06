"""R-A supplier keyword extraction and offer alignment guards."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError
from r_system_v2.ra.profit_engine import decimal_value
from r_system_v2.ra.providers import RAnalysisProviderBinding


SKILL_VERSION = "ra-supplier-keyword-2026-07-06"
SKILL_DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "ra_supplier_keyword_skill.md"

PRODUCT_TYPE_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("neck fan", "挂脖风扇", ("挂脖风扇", "挂脖扇", "neck fan", "neckband fan")),
    ("waist fan", "挂腰风扇", ("挂腰风扇", "挂腰扇", "waist fan")),
    ("shade sail", "遮阳帆", ("遮阳帆", "遮阳篷", "shade sail", "sun shade sail")),
    ("market umbrella", "庭院伞", ("庭院伞", "遮阳伞", "patio umbrella", "market umbrella")),
    ("dining table", "餐桌", ("餐桌", "dining table", "kitchen table")),
    ("tablecloth", "桌布", ("桌布", "tablecloth", "table cover")),
    ("label printer", "标签打印机", ("标签打印机", "label printer", "thermal printer")),
    ("milk frother", "打奶器", ("打奶器", "奶泡器", "milk frother")),
    ("cat tree", "猫爬架", ("猫爬架", "cat tree", "cat tower")),
    ("camping chair", "露营椅", ("露营椅", "camping chair")),
    ("camping table", "露营桌", ("露营桌", "camping table", "folding table")),
    ("outdoor storage box", "户外收纳箱", ("户外收纳箱", "甲板箱", "deck box")),
    ("garden hose", "花园水管", ("花园水管", "花园软管", "garden hose")),
    ("solar garden light", "太阳能庭院灯", ("太阳能庭院灯", "太阳能灯", "garden light")),
    ("anti slip tape", "防滑胶带", ("防滑胶带", "anti slip tape", "grip tape")),
    ("garden fence", "花园围栏", ("花园围栏", "动物围栏", "garden fence")),
    ("splash pad", "水上滑垫", ("水上滑垫", "水滑梯", "splash pad")),
    ("outdoor fan", "户外风扇", ("户外风扇", "吊扇", "outdoor fan")),
)

SHAPE_CONFLICTS: tuple[tuple[str, str], ...] = (
    ("挂脖", "挂腰"),
    ("neck", "waist"),
    ("餐桌", "桌布"),
    ("dining table", "tablecloth"),
    ("遮阳帆", "遮阳伞"),
    ("shade sail", "umbrella"),
    ("标签打印机", "标签纸"),
    ("label printer", "label paper"),
    ("打奶器", "奶粉"),
    ("frother", "milk powder"),
)

SIZE_PRICED_TERMS = (
    "遮阳帆",
    "遮阳篷",
    "桌布",
    "胶带",
    "围栏",
    "软管",
    "水管",
    "地垫",
    "防水布",
    "shade sail",
    "tablecloth",
    "tape",
    "hose",
    "fence",
    "mat",
    "tarp",
)

GENERIC_BRAND_WORDS = {
    "the",
    "and",
    "with",
    "for",
    "new",
    "best",
    "amazon",
    "prime",
    "brand",
    "generic",
}


def build_supplier_keyword_profile(
    db: Session | None,
    *,
    org_id: str | None,
    product: dict[str, Any],
) -> dict[str, Any]:
    fallback = _heuristic_profile(product)
    if db is None or not org_id or not _deepseek_keyword_enabled():
        return fallback

    try:
        api_key = RAnalysisProviderBinding(
            org_id=org_id,
            secret_manager=SecretManager(db_session=db),
        ).deepseek_key()
    except SecretManagerError:
        return fallback
    if not api_key.strip():
        return fallback

    try:
        response = _call_deepseek_keyword_profile(api_key=api_key, product=product)
    except Exception as exc:
        fallback["source"] = "heuristic_after_deepseek_error"
        fallback["error"] = str(exc)[:240]
        return fallback

    merged = {**fallback, **_dict_value(response)}
    merged["source"] = "deepseek"
    return sanitize_keyword_profile(merged, product=product)


def sanitize_keyword_profile(
    profile: dict[str, Any],
    *,
    product: dict[str, Any],
) -> dict[str, Any]:
    fallback = _heuristic_profile(product)
    brand = _clean_term(profile.get("brand") or fallback.get("brand"))
    forbidden = _dedupe_terms(
        [
            brand,
            *_list_value(profile.get("forbidden_terms")),
            *_list_value(fallback.get("forbidden_terms")),
        ]
    )
    product_type_zh = _clean_keyword(
        profile.get("product_type_zh") or fallback.get("product_type_zh"),
        forbidden_terms=forbidden,
    )
    if not product_type_zh:
        product_type_zh = str(fallback.get("product_type_zh") or "").strip()

    core_keywords = _dedupe_terms(
        [
            product_type_zh,
            *_list_value(profile.get("core_keywords_zh")),
            *_list_value(fallback.get("core_keywords_zh")),
        ]
    )
    core_keywords = [
        _clean_keyword(item, forbidden_terms=forbidden)
        for item in core_keywords
        if _clean_keyword(item, forbidden_terms=forbidden)
    ][:6]
    base = core_keywords[0] if core_keywords else product_type_zh

    search_queries = _dict_value(profile.get("search_queries"))
    cleaned_queries = {
        "1688": _query_list(search_queries.get("1688"), base=base, platform="1688", forbidden=forbidden),
        "pdd": _query_list(search_queries.get("pdd"), base=base, platform="pdd", forbidden=forbidden),
        "taobao": _query_list(search_queries.get("taobao"), base=base, platform="taobao", forbidden=forbidden),
        "jd": _query_list(search_queries.get("jd"), base=base, platform="jd", forbidden=forbidden),
    }

    pack_count = _int_value(profile.get("pack_count")) or _int_value(fallback.get("pack_count"))
    dimensions = _dict_value(profile.get("dimensions")) or _dict_value(fallback.get("dimensions"))
    raw_dimensions = _list_value(dimensions.get("raw")) or _list_value(fallback.get("dimensions", {}).get("raw"))
    parsed_dimensions = extract_dimensions_cm(" ".join(str(item) for item in raw_dimensions))
    if not parsed_dimensions:
        parsed_dimensions = extract_dimensions_cm(_joined_text(product.get("title"), product.get("title_zh")))
    requires_alignment = bool(dimensions.get("requires_alignment")) or _requires_size_alignment(
        _joined_text(product.get("title"), product.get("title_zh"), product_type_zh)
    )

    return {
        "skill_version": SKILL_VERSION,
        "source": str(profile.get("source") or fallback.get("source") or "heuristic"),
        "brand": brand,
        "forbidden_terms": forbidden,
        "product_type": str(profile.get("product_type") or fallback.get("product_type") or "").strip(),
        "product_type_zh": product_type_zh,
        "core_keywords_zh": core_keywords,
        "search_queries": cleaned_queries,
        "pack_count": pack_count,
        "dimensions": {
            "raw": raw_dimensions,
            "parsed_cm": parsed_dimensions,
            "requires_alignment": requires_alignment,
        },
        "attributes": _dict_value(profile.get("attributes")),
        "error": profile.get("error"),
    }


def evaluate_supplier_alignment(
    *,
    product: dict[str, Any],
    keyword_profile: dict[str, Any],
    supplier_title: str | None,
    supplier_snippet: str | None,
    raw_excerpt: str | None,
    unit_price_cny: Decimal | None,
) -> dict[str, Any]:
    combined = _joined_text(supplier_title, supplier_snippet, raw_excerpt)
    product_text = _joined_text(product.get("title"), product.get("title_zh"))
    product_type = str(keyword_profile.get("product_type_zh") or "").strip()
    core_terms = _list_value(keyword_profile.get("core_keywords_zh"))[:4]
    forbidden = _list_value(keyword_profile.get("forbidden_terms"))
    warnings: list[str] = []
    status = "match"
    score = 88

    forbidden_hits = [
        term for term in forbidden if term and _term_in_text(term, combined)
    ]
    if forbidden_hits:
        status = "mismatch"
        score = min(score, 20)
        warnings.append(f"供应商详情含品牌/商标词：{', '.join(forbidden_hits[:3])}")

    conflict = _shape_conflict(product_text, combined)
    if conflict:
        status = "mismatch"
        score = min(score, 25)
        warnings.append(f"产品形态冲突：{conflict[0]} / {conflict[1]}")

    if core_terms and not any(_term_in_text(term, combined) for term in core_terms):
        status = "review" if status == "match" else status
        score = min(score, 55)
        warnings.append("供应商标题/摘要未明确命中产品主体词。")

    quantity = _quantity_alignment(product=product, keyword_profile=keyword_profile, supplier_text=combined)
    cost_multiplier = decimal_value(quantity.get("cost_multiplier"))
    if quantity["status"] == "needs_review":
        status = "review" if status == "match" else status
        score = min(score, 58)
        warnings.append(str(quantity["reason"]))

    dimensions = _dimension_alignment(product=product, keyword_profile=keyword_profile, supplier_text=combined)
    if dimensions["status"] == "needs_review":
        status = "review" if status == "match" else status
        score = min(score, 56)
        warnings.append(str(dimensions["reason"]))
    elif dimensions.get("cost_multiplier"):
        cost_multiplier = _multiply_optional(cost_multiplier, decimal_value(dimensions.get("cost_multiplier")))

    adjusted_price = unit_price_cny
    if adjusted_price is not None and cost_multiplier is not None:
        adjusted_price = _money(adjusted_price * cost_multiplier)

    return {
        "match_status": status,
        "match_score": max(0, min(100, score)),
        "match_reason": "；".join(warnings) if warnings else "供应商主体、数量和尺寸通过基础校验。",
        "warnings": warnings,
        "quantity": quantity,
        "dimensions": dimensions,
        "cost_multiplier": _decimal_number(cost_multiplier),
        "raw_unit_price_cny": _decimal_number(unit_price_cny),
        "adjusted_unit_price_cny": _decimal_number(adjusted_price),
    }


def extract_pack_count(text: Any) -> int | None:
    source = str(text or "")
    patterns = (
        r"([1-9][0-9]{0,2})\s*(?:pack|packs|pcs|pieces|count|counts|panel|panels|roll|rolls|pair|pairs|set|sets)\b",
        r"([1-9][0-9]{0,2})\s*(?:件装|只装|个装|片装|套装|卷装|双装)",
        r"([1-9][0-9]{0,2})\s*(?:件|只|个|片|套|卷|双)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            parsed = _int_value(match.group(1))
            return parsed if parsed and parsed > 1 else None
    return None


def extract_dimensions_cm(text: Any) -> list[dict[str, Any]]:
    source = str(text or "").replace("×", "x").replace("*", "x")
    output: list[dict[str, Any]] = []
    pattern = re.compile(
        r"([0-9]+(?:\.[0-9]+)?)\s*x\s*([0-9]+(?:\.[0-9]+)?)(?:\s*x\s*([0-9]+(?:\.[0-9]+)?))?\s*(ft|feet|foot|in|inch|inches|cm|厘米|m|米|mm|毫米)\b",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(source):
        unit = match.group(4).lower()
        values = [
            _unit_to_cm(decimal_value(group), unit)
            for group in match.groups()[:3]
            if group is not None
        ]
        values = [value for value in values if value is not None]
        if len(values) >= 2:
            output.append(
                {
                    "raw": match.group(0),
                    "values_cm": [_decimal_number(value) for value in values],
                    "area_cm2": _decimal_number(values[0] * values[1]),
                }
            )
    return output


def _heuristic_profile(product: dict[str, Any]) -> dict[str, Any]:
    text = _joined_text(product.get("title_zh"), product.get("title"), product.get("category"))
    brand = _clean_term(product.get("brand")) or _infer_brand(product.get("title"))
    product_type, product_type_zh, terms = _infer_product_type(text)
    if not product_type_zh:
        product_type_zh = _fallback_keyword(product)
    forbidden = _dedupe_terms([brand])
    base = _clean_keyword(product_type_zh, forbidden_terms=forbidden) or product_type_zh
    pack_count = extract_pack_count(text)
    dimensions = extract_dimensions_cm(text)
    return {
        "skill_version": SKILL_VERSION,
        "source": "heuristic",
        "brand": brand,
        "forbidden_terms": forbidden,
        "product_type": product_type,
        "product_type_zh": base,
        "core_keywords_zh": _dedupe_terms([base, *terms])[:6],
        "search_queries": {
            "1688": _default_platform_queries(base, "1688"),
            "pdd": _default_platform_queries(base, "pdd"),
            "taobao": _default_platform_queries(base, "taobao"),
            "jd": _default_platform_queries(base, "jd"),
        },
        "pack_count": pack_count,
        "dimensions": {
            "raw": [item["raw"] for item in dimensions],
            "parsed_cm": dimensions,
            "requires_alignment": _requires_size_alignment(text),
        },
        "attributes": {},
    }


def _call_deepseek_keyword_profile(*, api_key: str, product: dict[str, Any]) -> dict[str, Any]:
    prompt = {
        "asin": product.get("asin"),
        "brand": product.get("brand"),
        "title": product.get("title"),
        "title_zh": product.get("title_zh"),
        "category": product.get("category"),
        "category_path": product.get("category_path"),
        "price": str(product.get("price") or ""),
        "instruction": "按 skill 抽取无品牌供应商搜索关键词和变体对齐要素，返回严格 JSON。",
    }
    body = {
        "model": os.getenv("RA_DEEPSEEK_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-chat")),
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": _skill_text() + "\n只返回 JSON，不要 Markdown。",
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    }
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=_deepseek_timeout_seconds()) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:240]
        raise RuntimeError(f"DeepSeek 关键词抽取失败：HTTP {exc.code} {detail}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"DeepSeek 关键词抽取失败：{exc}") from exc

    content = (
        payload.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    return _parse_json_object(str(content))


def _skill_text() -> str:
    try:
        return SKILL_DOC_PATH.read_text(encoding="utf-8")[:8000]
    except OSError:
        return "供应商搜索必须去品牌；数量和尺寸必须对齐；不足 3 个可靠供应商不生成正式利润。"


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if match:
        cleaned = match.group(0)
    parsed = json.loads(cleaned)
    return _dict_value(parsed)


def _query_list(value: Any, *, base: str, platform: str, forbidden: list[str]) -> list[str]:
    source = _list_value(value)
    if not source:
        source = _default_platform_queries(base, platform)
    cleaned = []
    for item in source:
        keyword = _clean_keyword(item, forbidden_terms=forbidden)
        if not keyword:
            continue
        cleaned.append(_cap_query(keyword))
    cleaned = _dedupe_terms(cleaned)
    if len(cleaned) < 2 and platform == "1688":
        cleaned.extend(_default_platform_queries(base, platform))
    return _dedupe_terms(cleaned)[:4]


def _default_platform_queries(base: str, platform: str) -> list[str]:
    keyword = _cap_query(base)
    if platform == "1688":
        return [
            f"{keyword} 一件代发",
            f"{keyword} 一件起批",
            f"{keyword} 批发 厂家",
            f"{keyword} 现货",
        ]
    if platform == "pdd":
        return [f"拼多多 {keyword}", f"{keyword} 拼多多 现货"]
    if platform == "taobao":
        return [f"淘宝 {keyword}", f"{keyword} 淘宝 同款"]
    if platform == "jd":
        return [f"京东 {keyword}", f"{keyword} 京东 现货"]
    return [keyword]


def _infer_product_type(text: str) -> tuple[str, str, tuple[str, ...]]:
    lowered = text.lower()
    for product_type, product_type_zh, terms in PRODUCT_TYPE_RULES:
        if any(term.lower() in lowered for term in terms):
            return product_type, product_type_zh, terms
    return "", "", ()


def _fallback_keyword(product: dict[str, Any]) -> str:
    title_zh = _clean_for_keyword(product.get("title_zh"))
    if title_zh:
        for separator in ("，", ",", " - ", "-", "，", "（", "("):
            title_zh = title_zh.split(separator, 1)[0].strip()
        if 2 <= len(title_zh) <= 16:
            return title_zh
        return title_zh[:16]
    title = _clean_for_keyword(product.get("title"))
    words = [word for word in re.split(r"\s+", title) if word and not _looks_like_brand(word)]
    return " ".join(words[:4])[:48] or "supplier product"


def _infer_brand(title: Any) -> str:
    words = re.split(r"\s+", str(title or "").strip())
    if not words:
        return ""
    first = re.sub(r"[^A-Za-z0-9-]", "", words[0])
    if _looks_like_brand(first):
        return first
    return ""


def _looks_like_brand(word: str) -> bool:
    cleaned = word.strip()
    if len(cleaned) < 3:
        return False
    lowered = cleaned.lower()
    if lowered in GENERIC_BRAND_WORDS:
        return False
    return bool(re.match(r"^[A-Z][A-Za-z0-9-]{2,}$", cleaned) or re.match(r"^[A-Z0-9-]{4,}$", cleaned))


def _quantity_alignment(
    *,
    product: dict[str, Any],
    keyword_profile: dict[str, Any],
    supplier_text: str,
) -> dict[str, Any]:
    amazon_count = _int_value(keyword_profile.get("pack_count")) or extract_pack_count(
        _joined_text(product.get("title"), product.get("title_zh"))
    )
    supplier_count = extract_pack_count(supplier_text)
    if not amazon_count or amazon_count <= 1:
        return {
            "status": "not_required",
            "amazon_pack_count": amazon_count or 1,
            "supplier_pack_count": supplier_count,
            "cost_multiplier": None,
            "reason": None,
        }
    if not supplier_count:
        return {
            "status": "needs_review",
            "amazon_pack_count": amazon_count,
            "supplier_pack_count": None,
            "cost_multiplier": None,
            "reason": f"亚马逊为 {amazon_count} 件/套装，供应商未明确同等数量。",
        }
    multiplier = Decimal(amazon_count) / Decimal(supplier_count)
    return {
        "status": "aligned",
        "amazon_pack_count": amazon_count,
        "supplier_pack_count": supplier_count,
        "cost_multiplier": _decimal_number(multiplier),
        "reason": f"按 {amazon_count}:{supplier_count} 数量换算成本。",
    }


def _dimension_alignment(
    *,
    product: dict[str, Any],
    keyword_profile: dict[str, Any],
    supplier_text: str,
) -> dict[str, Any]:
    dimensions = _dict_value(keyword_profile.get("dimensions"))
    requires = bool(dimensions.get("requires_alignment")) or _requires_size_alignment(
        _joined_text(product.get("title"), product.get("title_zh"))
    )
    amazon_dims = _list_value(dimensions.get("parsed_cm")) or extract_dimensions_cm(
        _joined_text(product.get("title"), product.get("title_zh"))
    )
    supplier_dims = extract_dimensions_cm(supplier_text)
    if not requires:
        return {
            "status": "not_required",
            "amazon_dimensions": amazon_dims,
            "supplier_dimensions": supplier_dims,
            "cost_multiplier": None,
            "reason": None,
        }
    if not amazon_dims:
        return {
            "status": "needs_review",
            "amazon_dimensions": [],
            "supplier_dimensions": supplier_dims,
            "cost_multiplier": None,
            "reason": "该产品按尺寸影响成本，但亚马逊尺寸未解析成功。",
        }
    if not supplier_dims:
        return {
            "status": "needs_review",
            "amazon_dimensions": amazon_dims,
            "supplier_dimensions": [],
            "cost_multiplier": None,
            "reason": "该产品按尺寸影响成本，供应商未明确同等尺寸。",
        }

    amazon_area = decimal_value(amazon_dims[0].get("area_cm2"))
    supplier_area = decimal_value(supplier_dims[0].get("area_cm2"))
    multiplier = None
    if amazon_area is not None and supplier_area is not None and supplier_area > 0:
        ratio = amazon_area / supplier_area
        if Decimal("0.85") <= ratio <= Decimal("1.15"):
            multiplier = Decimal("1")
        elif Decimal("0.25") <= ratio <= Decimal("4"):
            multiplier = ratio
        else:
            return {
                "status": "needs_review",
                "amazon_dimensions": amazon_dims,
                "supplier_dimensions": supplier_dims,
                "cost_multiplier": None,
                "reason": "供应商尺寸与亚马逊尺寸差异过大，不能自动换算利润。",
            }
    return {
        "status": "aligned",
        "amazon_dimensions": amazon_dims,
        "supplier_dimensions": supplier_dims,
        "cost_multiplier": _decimal_number(multiplier),
        "reason": "尺寸已对齐或按面积比例换算。",
    }


def _shape_conflict(product_text: str, supplier_text: str) -> tuple[str, str] | None:
    p = product_text.lower()
    s = supplier_text.lower()
    for left, right in SHAPE_CONFLICTS:
        left_l = left.lower()
        right_l = right.lower()
        if left_l in p and right_l in s:
            return left, right
        if right_l in p and left_l in s:
            return right, left
    return None


def _requires_size_alignment(text: str) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in SIZE_PRICED_TERMS)


def _unit_to_cm(value: Decimal | None, unit: str) -> Decimal | None:
    if value is None:
        return None
    normalized = unit.lower()
    if normalized in {"cm", "厘米"}:
        return value
    if normalized in {"m", "米"}:
        return value * Decimal("100")
    if normalized in {"mm", "毫米"}:
        return value / Decimal("10")
    if normalized in {"in", "inch", "inches"}:
        return value * Decimal("2.54")
    if normalized in {"ft", "feet", "foot"}:
        return value * Decimal("30.48")
    return value


def _multiply_optional(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None:
        return right
    if right is None:
        return left
    return left * right


def _clean_keyword(value: Any, *, forbidden_terms: list[str]) -> str:
    text = _clean_for_keyword(value)
    for term in forbidden_terms:
        if not term:
            continue
        text = re.sub(re.escape(term), " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bB0[A-Z0-9]{8}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:amazon|prime|official|旗舰店|官方|品牌)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _clean_for_keyword(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"[^\w\u4e00-\u9fff\s./x×*-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _clean_term(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^\w\u4e00-\u9fff-]", "", text)
    if len(text) < 2 or text.lower() in GENERIC_BRAND_WORDS:
        return ""
    return text[:60]


def _cap_query(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if re.search(r"[\u4e00-\u9fff]", cleaned):
        return cleaned[:28]
    return " ".join(cleaned.split()[:8])[:64]


def _joined_text(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            parts.append(json.dumps(value, ensure_ascii=False))
        else:
            parts.append(str(value))
    return " ".join(parts)


def _term_in_text(term: str, text: str) -> bool:
    if not term:
        return False
    return term.lower() in text.lower()


def _dedupe_terms(values: list[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = str(value or "").strip()
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(term)
    return output


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def _int_value(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _decimal_number(value: Any) -> float | None:
    parsed = decimal_value(value)
    return float(parsed) if parsed is not None else None


def _deepseek_keyword_enabled() -> bool:
    return os.getenv("RA_DEEPSEEK_KEYWORD_ENABLED", "1").strip().lower() not in {"0", "false", "no"}


def _deepseek_timeout_seconds() -> float:
    value = os.getenv("RA_DEEPSEEK_KEYWORD_TIMEOUT_SECONDS")
    if not value:
        return 12.0
    try:
        parsed = float(value)
    except ValueError:
        return 12.0
    return max(3.0, min(parsed, 30.0))
