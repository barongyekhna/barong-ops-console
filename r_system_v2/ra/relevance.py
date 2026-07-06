"""Query-to-product relevance gate for R-A candidate selection.

This layer is intentionally query-scoped: it decides whether an R-W product is
useful for the current R-A analysis request, without mutating or deleting the
source product in R-W.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Literal


RelevanceStatus = Literal[
    "exact_match",
    "variant_match",
    "accessory_only",
    "consumable_only",
    "replacement_part_only",
    "unrelated",
]


@dataclass(frozen=True)
class ProductRelevance:
    status: RelevanceStatus
    score: int
    should_process: bool
    reason: str
    matched_terms: tuple[str, ...] = ()
    blocked_terms: tuple[str, ...] = ()

    def to_product_fields(self) -> dict[str, object]:
        return {
            "relevance_status": self.status,
            "relevance_score": self.score,
            "relevance_should_process": self.should_process,
            "relevance_reason": self.reason,
            "relevance_matched_terms": list(self.matched_terms),
            "relevance_blocked_terms": list(self.blocked_terms),
        }


@dataclass(frozen=True)
class QueryIntent:
    raw_query: str
    terms: tuple[str, ...]
    product_groups: tuple[str, ...]
    accessory_intent: bool
    consumable_intent: bool
    replacement_part_intent: bool


PRODUCT_GROUPS: dict[str, tuple[str, ...]] = {
    "table": ("餐桌", "饭桌", "桌子", "折叠桌", "露营桌", "dining table", "kitchen table", "folding table", "camping table", "picnic table", "table"),
    "chair": ("椅子", "座椅", "凳子", "chair", "stool", "bench"),
    "shelf_rack": ("架子", "货架", "置物架", "收纳架", "shelf", "rack", "stand"),
    "storage_box": ("收纳盒", "收纳箱", "储物箱", "盒子", "storage box", "organizer", "bin", "basket"),
    "lamp_light": ("灯", "台灯", "庭院灯", "露营灯", "灯具", "light", "lamp", "lantern"),
    "bed": ("床", "宠物窝", "宠物床", "bed", "cot"),
    "tent": ("帐篷", "tent"),
    "bag": ("包", "背包", "收纳袋", "袋", "bag", "backpack", "pouch"),
    "printer_machine": ("打印机", "标签机", "机器", "设备", "printer", "label maker", "machine", "device"),
    "bottle_cup": ("水杯", "杯子", "瓶", "bottle", "cup", "mug", "tumbler"),
    "tool": ("工具", "tool", "kit"),
}

ACCESSORY_TERMS = (
    "cover",
    "case",
    "sleeve",
    "protector",
    "liner",
    "mat",
    "pad",
    "cushion",
    "runner",
    "cloth",
    "tablecloth",
    "table cloth",
    "placemat",
    "place mat",
    "napkin",
    "paper towel",
    "decoration",
    "decor",
    "sticker",
    "label",
    "holder",
    "mount",
    "strap",
    "insert",
    "organizer insert",
    "配件",
    "附件",
    "保护套",
    "外壳",
    "套",
    "罩",
    "盖",
    "垫",
    "坐垫",
    "脚垫",
    "桌布",
    "台布",
    "桌旗",
    "桌垫",
    "餐垫",
    "餐巾",
    "纸巾",
    "装饰",
    "贴纸",
    "标签",
    "支架",
    "挂架",
)

CONSUMABLE_TERMS = (
    "food",
    "treat",
    "snack",
    "supplement",
    "vitamin",
    "capsule",
    "tablet",
    "liquid",
    "powder",
    "spray",
    "aerosol",
    "repellent",
    "pesticide",
    "insecticide",
    "refill",
    "cartridge",
    "ink",
    "食物",
    "食品",
    "零食",
    "粮",
    "狗粮",
    "猫粮",
    "保健品",
    "药",
    "药品",
    "液体",
    "粉末",
    "喷雾",
    "杀虫剂",
    "灭蚊",
    "补充装",
    "替换装",
    "墨盒",
)

REPLACEMENT_PART_TERMS = (
    "replacement",
    "refill",
    "part",
    "parts",
    "filter",
    "blade",
    "wheel",
    "adapter",
    "cord",
    "cable",
    "battery",
    "charger",
    "替换",
    "替换件",
    "配件",
    "零件",
    "滤芯",
    "刀片",
    "轮子",
    "转接头",
    "线缆",
    "电池",
    "充电器",
)

NEGATIVE_CONTEXT_HINTS = (
    "for ",
    "compatible with",
    "fits ",
    "replacement for",
    "适用于",
    "兼容",
    "替换",
)


def classify_product_relevance(query: str, product: dict[str, Any]) -> ProductRelevance:
    intent = parse_query_intent(query)
    product_text = _product_text(product)
    matched_terms = _matched_terms(intent.terms, product_text)
    query_group_match = _product_group_match(intent.product_groups, product_text)

    consumable_hits = _contains_terms(product_text, CONSUMABLE_TERMS)
    if consumable_hits and not intent.consumable_intent:
        return ProductRelevance(
            status="consumable_only",
            score=0,
            should_process=False,
            reason=f"当前搜索目标不是食品/液体/粉末/喷雾/耗材，产品命中：{', '.join(consumable_hits[:4])}。",
            matched_terms=matched_terms,
            blocked_terms=tuple(consumable_hits),
        )

    replacement_hits = _contains_terms(product_text, REPLACEMENT_PART_TERMS)
    if replacement_hits and not intent.replacement_part_intent and _negative_context(product_text):
        return ProductRelevance(
            status="replacement_part_only",
            score=0,
            should_process=False,
            reason=f"当前搜索目标不是替换件/零件，产品更像配件或替换件：{', '.join(replacement_hits[:4])}。",
            matched_terms=matched_terms,
            blocked_terms=tuple(replacement_hits),
        )

    accessory_hits = _contains_terms(product_text, ACCESSORY_TERMS)
    if accessory_hits and not intent.accessory_intent:
        return ProductRelevance(
            status="accessory_only",
            score=0,
            should_process=False,
            reason=f"当前搜索目标不是配件/装饰/保护件，产品标题或类目命中：{', '.join(accessory_hits[:4])}。",
            matched_terms=matched_terms,
            blocked_terms=tuple(accessory_hits),
        )

    if query_group_match:
        score = 90 + min(10, len(matched_terms) * 2)
        return ProductRelevance(
            status="exact_match" if matched_terms else "variant_match",
            score=score,
            should_process=True,
            reason="产品主体与搜索词的产品类型一致。",
            matched_terms=matched_terms,
        )

    if matched_terms:
        score = 62 + min(20, len(matched_terms) * 4)
        return ProductRelevance(
            status="variant_match",
            score=score,
            should_process=True,
            reason="产品标题/类目/source_query 命中搜索词，未发现配件或耗材偏题信号。",
            matched_terms=matched_terms,
        )

    return ProductRelevance(
        status="unrelated",
        score=0,
        should_process=False,
        reason="产品标题、类目和来源关键词与当前搜索目标没有足够相关性。",
    )


def parse_query_intent(query: str) -> QueryIntent:
    cleaned = _clean(query)
    terms = tuple(_dedupe([cleaned, *_split_terms(cleaned)]))
    haystack = f" {cleaned.lower()} "
    product_groups = tuple(
        group
        for group, aliases in PRODUCT_GROUPS.items()
        if any(_term_in_text(alias, haystack) for alias in aliases)
    )
    return QueryIntent(
        raw_query=cleaned,
        terms=terms,
        product_groups=product_groups,
        accessory_intent=bool(_contains_terms(haystack, ACCESSORY_TERMS)),
        consumable_intent=bool(_contains_terms(haystack, CONSUMABLE_TERMS)),
        replacement_part_intent=bool(_contains_terms(haystack, REPLACEMENT_PART_TERMS)),
    )


def _product_group_match(groups: tuple[str, ...], product_text: str) -> bool:
    if not groups:
        return False
    for group in groups:
        aliases = PRODUCT_GROUPS.get(group, ())
        if any(_term_in_text(alias, product_text) for alias in aliases):
            return True
    return False


def _matched_terms(terms: tuple[str, ...], product_text: str) -> tuple[str, ...]:
    return tuple(term for term in terms if len(term) >= 2 and _term_in_text(term, product_text))


def _contains_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for term in terms:
        if _term_in_text(term, text):
            hits.append(term)
    return hits


def _term_in_text(term: str, text: str) -> bool:
    cleaned = _clean(term)
    if not cleaned:
        return False
    if _has_cjk(cleaned):
        return cleaned in text
    return re.search(rf"(?<![a-z0-9]){re.escape(cleaned)}(?![a-z0-9])", text) is not None


def _negative_context(text: str) -> bool:
    return any(hint in text for hint in NEGATIVE_CONTEXT_HINTS)


def _product_text(product: dict[str, Any]) -> str:
    values = [
        product.get("title"),
        product.get("title_zh"),
        product.get("source_query"),
        product.get("category"),
        product.get("category_id"),
        product.get("category_path"),
        product.get("brand"),
    ]
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            parts.append(json.dumps(value, ensure_ascii=False))
        else:
            parts.append(str(value))
    return _clean(" ".join(parts))


def _split_terms(query: str) -> list[str]:
    parts = [part for part in re.split(r"[\s,，/|;；]+", query) if len(part) >= 2]
    if _has_cjk(query):
        for size in (4, 3, 2):
            parts.extend(query[index : index + size] for index in range(0, max(0, len(query) - size + 1)))
    return parts


def _clean(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^\w\u4e00-\u9fff\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output
