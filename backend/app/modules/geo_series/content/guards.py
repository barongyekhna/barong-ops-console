"""Output guards for generated GEO content (fail-closed).

Reuses K's tested primitives — brand blacklist + CJK detection — and adds a
numeric-grounding check: any number an AI writes into guide copy must appear in
the product's own verified evidence corpus (specs / selling points / package /
dimensions). This is the "evidence_guard 兜底" for the GEO content engine: it
stops the model from inventing competitor figures or unsupported specs, the same
class of bug the K FAQ fix addressed at the product page.

Brand rule (死命令): the ONLY brand allowed in any output is SITE_BRAND.
"""

from __future__ import annotations

import re
from typing import Any

from ...k_series.product_knowledge.brand_guard import (
    SITE_BRAND,
    blacklist_violations,
)
from ...k_series.product_knowledge.buyer_display import contains_cjk

_NUMBER = re.compile(r"(?<!\d)\d[\d,]*(?:\.\d+)?")
# Non-spec numerics that legitimately appear in prose and never need spec backing.
_GROUNDING_WHITELIST = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "0"}


def _canonical_number(token: str) -> str:
    return token.replace(",", "").rstrip("0").rstrip(".") if "." in token else token.replace(",", "")


def evidence_number_corpus(*fact_texts: Any) -> set[str]:
    """All numeric tokens present in the product's verified evidence."""
    corpus: set[str] = set()
    for text in fact_texts:
        for match in _NUMBER.finditer(str(text or "")):
            corpus.add(_canonical_number(match.group(0)))
    return corpus


def _numbers_in(text: str) -> set[str]:
    return {_canonical_number(m.group(0)) for m in _NUMBER.finditer(text or "")}


def item_text_surfaces(item: dict[str, Any]) -> list[tuple[str, str]]:
    """Buyer-facing text fields of a generated content item (label -> text)."""
    surfaces: list[tuple[str, str]] = []
    title = str(item.get("title") or "").strip()
    if title:
        surfaces.append(("title", title))
    for idx, section in enumerate(item.get("sections") or []):
        if isinstance(section, dict):
            for field in ("heading", "body"):
                value = str(section.get(field) or "").strip()
                if value:
                    surfaces.append((f"section[{idx}].{field}", value))
    for idx, block in enumerate(item.get("answer_blocks") or []):
        if isinstance(block, dict):
            for field in ("question", "answer"):
                value = str(block.get(field) or "").strip()
                if value:
                    surfaces.append((f"answer[{idx}].{field}", value))
    seo = item.get("seo")
    if isinstance(seo, dict):
        for field in ("title", "meta_description"):
            value = str(seo.get(field) or "").strip()
            if value:
                surfaces.append((f"seo.{field}", value))
    return surfaces


def audit_content_item(
    item: dict[str, Any],
    *,
    forbidden_terms: list[str],
    evidence_numbers: set[str],
) -> dict[str, Any]:
    """Fail-closed audit of one generated content item.

    Returns ``{clean, brand_violations, cjk_surfaces, ungrounded_numbers}``.
    ``clean`` is True only when there are no third-party brands, no CJK leakage,
    and every spec-shaped number is backed by the evidence corpus.
    """
    surfaces = item_text_surfaces(item)

    brand = blacklist_violations(surfaces, forbidden_terms)

    cjk_surfaces = [label for label, text in surfaces if contains_cjk(text)]

    ungrounded: list[dict[str, str]] = []
    allowed = evidence_numbers | _GROUNDING_WHITELIST
    for label, text in surfaces:
        for token in _numbers_in(text) - allowed:
            ungrounded.append({"surface": label, "number": token})

    clean = not brand and not cjk_surfaces and not ungrounded
    return {
        "clean": clean,
        "site_brand": SITE_BRAND,
        "brand_violations": brand,
        "cjk_surfaces": cjk_surfaces,
        "ungrounded_numbers": ungrounded,
    }


__all__ = [
    "evidence_number_corpus",
    "item_text_surfaces",
    "audit_content_item",
]
