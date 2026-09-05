"""帖子审计：事实门 + 品牌门 + 平台规则，一次算完落 ``brand_audit_json``。

复用 ``content_core.guards.audit_content_item``（品牌黑名单 / CJK / 数字接地 /
算式核验）；社媒多出来的三样——``facts_used`` 能不能解析、口径黑名单、平台规则
（标签数、首行长度）——折进 ``brand_violations``，surface 分别叫
``facts_used`` / ``phrase`` / ``platform``，这样指纹机制和人工放行照样管用，
``clean`` 仍然只由 ``recompute_audit_clean`` 一处决定。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from ..content_core.facts.models import CraftFact
from ..content_core.facts.service import grounding_texts
from ..content_core.guards import audit_content_item, evidence_number_corpus, recompute_audit_clean
from ..geo_series.content.models import GeoContentItem
from ..k_series.product_knowledge.brand_guard import (
    _product_own_words,
    _resolve_chat_key,
    ai_text_violations,
    normalized_brand_terms,
)
from ..k_series.product_knowledge.buyer_display import buyer_display_structured_specs
from ..k_series.product_knowledge.evidence_guard import canonical_package_includes
from ..k_series.product_knowledge.models import KProductKnowledgeProduct
from .constants import FORBIDDEN_PHRASES, PILLAR_BRAND
from .profiles import PlatformProfile

logger = logging.getLogger(__name__)

_NUMBER = re.compile(r"(?<!\d)\d[\d,]*(?:\.\d+)?")
_PATH_INDEX = re.compile(r"^([a-zA-Z_][\w]*)\[(\d+)\]$")


# ---------------------------------------------------------------- 快照与语料


def approved_selling_points(product: KProductKnowledgeProduct | None) -> list[str]:
    payload = getattr(product, "selling_points_approved_json", None)
    if not isinstance(payload, dict) or payload.get("review_status") != "approved":
        return []
    bullets = payload.get("bullets")
    return [str(b.get("text") or "").strip() for b in bullets or [] if isinstance(b, dict) and str(b.get("text") or "").strip()]


def product_snapshot(product: KProductKnowledgeProduct | None) -> dict[str, Any]:
    if product is None:
        return {}
    specs = buyer_display_structured_specs(product.structured_specs_json)
    return {
        "sku": product.sku,
        "product_name_en": product.product_name_en,
        "product_type": product.product_type,
        "primary_use_case_en": product.primary_use_case_en,
        "target_customer_en": product.target_customer_en,
        "primary_keyword": product.primary_keyword,
        "secondary_keywords_json": product.secondary_keywords_json,
        "long_tail_keywords_json": product.long_tail_keywords_json,
        "structured_specs_json": specs,
        "selling_points": approved_selling_points(product),
        "package_includes_json": canonical_package_includes(
            getattr(product, "package_includes_json", None), product.structured_specs_json
        ),
        "dimensions_json": product.dimensions_json,
        "weight_json": product.weight_json,
        "certifications_json": product.certifications_json,
        "warranty_note_en": product.warranty_note_en,
        "safety_note_en": product.safety_note_en,
        "stock_status": product.stock_status,
    }


def guide_snapshot(guide: GeoContentItem | None) -> dict[str, Any]:
    if guide is None:
        return {}
    body = guide.body_json if isinstance(guide.body_json, dict) else {}
    return {
        "title": guide.title,
        "item_type": guide.item_type,
        "sections": body.get("sections") or [],
        "answer_blocks": body.get("answer_blocks") or [],
        "published_url": guide.published_url,
    }


def facts_snapshot(facts: list[CraftFact]) -> dict[str, dict[str, Any]]:
    return {
        str(f.id): {"topic": f.topic, "claim": f.claim, "detail": f.detail, "value": f.value, "unit": f.unit}
        for f in facts
    }


def evidence_numbers(
    *, product: KProductKnowledgeProduct | None, guide: GeoContentItem | None, facts: list[CraftFact]
) -> set[str]:
    snap = product_snapshot(product)
    gsnap = guide_snapshot(guide)
    return evidence_number_corpus(
        snap.get("structured_specs_json"),
        # 买家展示层会过滤掉它不认识的规格键；原始规格里的数字同样是 K 里核过的
        # 真事实，一并进语料，别让「展示层没收录」被误判成「编造」。
        getattr(product, "structured_specs_json", None),
        snap.get("selling_points"),
        snap.get("package_includes_json"),
        snap.get("dimensions_json"),
        snap.get("weight_json"),
        gsnap.get("sections"),
        gsnap.get("answer_blocks"),
        *grounding_texts(facts),
    )


# ---------------------------------------------------------------- facts_used 解析


def _walk(value: Any, parts: list[str]) -> bool:
    for part in parts:
        match = _PATH_INDEX.match(part)
        if match:
            key, idx = match.group(1), int(match.group(2))
            if isinstance(value, dict):
                value = value.get(key)
            elif hasattr(value, key):
                value = getattr(value, key)
            else:
                return False
            if not isinstance(value, list) or idx >= len(value):
                return False
            value = value[idx]
            continue
        if isinstance(value, dict):
            if part not in value:
                return False
            value = value[part]
        elif hasattr(value, part):
            value = getattr(value, part)
        else:
            return False
    return value not in (None, "", [], {})


def resolve_facts_used(
    entries: Any,
    *,
    product: KProductKnowledgeProduct | None,
    guide: GeoContentItem | None,
    facts_by_id: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """把 ``facts_used`` 每条路径解析回真相源。返回 (resolved, unresolved)。"""
    resolved: list[str] = []
    unresolved: list[str] = []
    snap = product_snapshot(product)
    gsnap = guide_snapshot(guide)
    for raw in entries if isinstance(entries, list) else []:
        entry = str(raw or "").strip()
        if not entry:
            continue
        head, _, rest = entry.partition(".")
        parts = [p for p in rest.split(".") if p] if rest else []
        ok = False
        if head == "k":
            ok = bool(parts) and (_walk(snap, parts) or _walk(product, parts))
        elif head in ("geo", "guide"):
            ok = bool(parts) and _walk(gsnap, parts)
        elif head in ("craft_facts", "craft_fact", "fact"):
            ok = bool(parts) and parts[0] in facts_by_id
        (resolved if ok else unresolved).append(entry)
    return resolved, unresolved


# ---------------------------------------------------------------- 审计主体


def desk_item(post_fields: dict[str, Any]) -> dict[str, Any]:
    """帖子摊成内容台 / guards 认识的形状（title + sections + seo）。"""
    caption = str(post_fields.get("caption") or "")
    first_line = str(post_fields.get("first_line") or "")
    hashtags = post_fields.get("hashtags") or []
    sections: list[dict[str, str]] = []
    if first_line:
        sections.append({"heading": "First line", "body": first_line})
    if caption:
        sections.append({"heading": "Caption", "body": caption})
    alt = str(post_fields.get("alt_text") or "")
    if alt:
        sections.append({"heading": "Alt text", "body": alt})
    for idx, overlay in enumerate(post_fields.get("overlay_texts") or []):
        if str(overlay or "").strip():
            sections.append({"heading": f"Overlay {idx + 1}", "body": str(overlay)})
    if hashtags:
        sections.append({"heading": "Hashtags", "body": " ".join(f"#{h}" for h in hashtags)})
    return {
        "title": str(post_fields.get("title") or ""),
        "sections": sections,
        "answer_blocks": [],
        "seo": {"title": str(post_fields.get("title") or ""), "meta_description": str(post_fields.get("cta") or "")},
        "derived_numbers": post_fields.get("derived_numbers") or [],
    }


def _platform_violations(post_fields: dict[str, Any], profile: PlatformProfile) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    hashtags = post_fields.get("hashtags") or []
    if len(hashtags) > profile.hashtags_max:
        out.append({"surface": "platform", "term": "hashtags", "evidence": f"{len(hashtags)} > {profile.hashtags_max}"})
    first_line = str(post_fields.get("first_line") or "")
    if profile.first_line_max and len(first_line) > profile.first_line_max:
        out.append({"surface": "platform", "term": "first_line", "evidence": f"{len(first_line)} > {profile.first_line_max}"})
    title = str(post_fields.get("title") or "")
    if profile.title_max and len(title) > profile.title_max:
        out.append({"surface": "platform", "term": "title", "evidence": f"{len(title)} > {profile.title_max}"})
    alt = str(post_fields.get("alt_text") or "")
    if len(alt) > profile.alt_max:
        out.append({"surface": "platform", "term": "alt_text", "evidence": f"{len(alt)} > {profile.alt_max}"})
    keyword = str(post_fields.get("keyword_primary") or "").strip().lower()
    if keyword:
        head = (title[: profile.title_visible] if profile.title_visible else first_line).lower()
        if head and keyword not in head:
            out.append({"surface": "platform", "term": "keyword_position", "evidence": "主关键词不在可见前段"})
    return out


def _phrase_violations(item: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    texts = [item.get("title") or ""] + [s.get("body", "") for s in item.get("sections") or []]
    joined = " ".join(str(t) for t in texts).lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in joined:
            out.append({"surface": "phrase", "term": phrase, "evidence": "口径黑名单"})
    return out


def audit_post(
    db: Session,
    *,
    post_fields: dict[str, Any],
    pillar: str,
    profile: PlatformProfile,
    product: KProductKnowledgeProduct | None,
    guide: GeoContentItem | None,
    facts: list[CraftFact],
    previous_audit: dict[str, Any] | None,
    user: Any | None,
    ai_check: bool = True,
) -> dict[str, Any]:
    item = desk_item(post_fields)
    forbidden = normalized_brand_terms(product) if product is not None else []
    numbers = evidence_numbers(product=product, guide=guide, facts=facts)
    audit = audit_content_item(item, forbidden_terms=forbidden, evidence_numbers=numbers, previous_audit=previous_audit)

    # facts_used：空而正文有数字 → 违规；每条路径解析不到 → 违规
    resolved, unresolved = resolve_facts_used(
        post_fields.get("facts_used"), product=product, guide=guide, facts_by_id=facts_snapshot(facts)
    )
    audit["facts_used_resolved"] = resolved
    audit["facts_used_unresolved"] = unresolved
    text_blob = " ".join(s.get("body", "") for s in item["sections"]) + " " + item["title"]
    has_numbers = bool(set(_NUMBER.findall(text_blob)) - {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "0"})
    extra: list[dict[str, str]] = []
    if not resolved and has_numbers and pillar != PILLAR_BRAND:
        extra.append({"surface": "facts_used", "term": "empty", "evidence": "正文有数字但 facts_used 为空"})
    extra += [{"surface": "facts_used", "term": path, "evidence": "解析不到真相源"} for path in unresolved]
    extra += _phrase_violations(item)
    extra += _platform_violations(post_fields, profile)

    if ai_check:
        try:
            key = _resolve_chat_key(db, user)
            surfaces = [(f"section[{i}].body", s["body"]) for i, s in enumerate(item["sections"])]
            if item["title"]:
                surfaces.insert(0, ("title", item["title"]))
            own_words = _product_own_words(product) if product is not None else set()
            extra += ai_text_violations(key, surfaces, own_words)
        except Exception as exc:  # noqa: BLE001 - fail-closed，但可被人工放行
            logger.warning("SM AI text audit unavailable: %s", exc)
            extra.append({"surface": "ai_audit", "term": "unavailable", "evidence": str(exc)[:200]})

    audit["brand_violations"] = list(audit.get("brand_violations") or []) + extra
    return recompute_audit_clean(audit)


__all__ = [
    "approved_selling_points",
    "audit_post",
    "desk_item",
    "evidence_numbers",
    "facts_snapshot",
    "guide_snapshot",
    "product_snapshot",
    "resolve_facts_used",
]
