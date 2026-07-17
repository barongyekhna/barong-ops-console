"""Deterministic evidence guards for customer-facing PDP claims."""

from __future__ import annotations

import html
import re
from typing import Any


_TITLE_SEPARATORS = re.compile(r"\s*(?:\||—|–|•|:)\s*")
_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_UNTRUSTED_IDENTITY_CLAIMS = {
    "windproof",
    "waterproof",
    "safe",
    "safety",
    "indoor",
    "indoors",
    "home",
    "durable",
    "lightweight",
    "compact",
    "certified",
    "guaranteed",
}


def _claim_tokens(value: Any) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN.findall(html.unescape(str(value or "")))
        if token.casefold() not in _STOPWORDS
    }


def _flatten_text(value: Any) -> list[str]:
    if isinstance(value, dict):
        texts: list[str] = []
        for key, nested in value.items():
            if key in {"source", "url", "platform"}:
                continue
            texts.extend(_flatten_text(nested))
        return texts
    if isinstance(value, list):
        texts: list[str] = []
        for nested in value:
            texts.extend(_flatten_text(nested))
        return texts
    if value is None or isinstance(value, bool):
        return []
    return [str(value)]


def title_evidence_corpus(
    *,
    product_name: str | None,
    product_type: str | None,
    site_brand: str,
    approved_selling_points: dict[str, Any],
    structured_specs: dict[str, Any] | None,
) -> set[str]:
    # Identity text is needed to retain the product noun, but legacy names may
    # themselves contain unsupported modifiers. Never let those modifiers
    # self-prove merely because they appeared in the old title.
    identity_tokens = _claim_tokens(product_name or "") | _claim_tokens(
        product_type or ""
    )
    tokens = identity_tokens - _UNTRUSTED_IDENTITY_CLAIMS
    tokens.update(_claim_tokens(site_brand))
    texts: list[str] = []
    for bullet in approved_selling_points.get("bullets") or []:
        if isinstance(bullet, dict) and bullet.get("verification_status") == "verified":
            texts.append(str(bullet.get("text") or ""))
    texts.extend(_flatten_text(structured_specs or {}))
    for text in texts:
        tokens.update(_claim_tokens(text))
    return tokens


def _neutral_fallback(product_name: str | None, product_type: str | None) -> str:
    original = re.sub(
        r"\s+", " ", html.unescape(str(product_name or product_type or "Product"))
    ).strip()
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9&'/-]*", original)
    kept = [
        word
        for word in words
        if word.casefold().strip("-/") not in _UNTRUSTED_IDENTITY_CLAIMS
    ]
    return " ".join(kept).strip() or "Product"


def project_approved_selling_points(
    result: dict[str, Any],
    approved_selling_points: list[dict[str, Any]],
) -> dict[str, Any]:
    """Make customer-facing bullet grids an exact projection of approvals."""

    output = dict(result)
    approved_text = [
        re.sub(r"\s+", " ", html.unescape(str(item.get("text") or ""))).strip()
        for item in approved_selling_points
        if isinstance(item, dict)
        and item.get("verification_status") == "verified"
        and str(item.get("text") or "").strip()
    ]
    if isinstance(output.get("product_page_copy"), dict):
        product_page_copy = dict(output["product_page_copy"])
        product_page_copy["key_bullets"] = approved_text
        output["product_page_copy"] = product_page_copy
    if isinstance(output.get("listing_copy"), dict):
        listing_copy = dict(output["listing_copy"])
        listing_copy["bullet_points"] = approved_text
        output["listing_copy"] = listing_copy
    output["selling_points_projection"] = {
        "source": "selling_points_approved",
        "count": len(approved_text),
        "exact": True,
    }
    return output


def _supported_title(
    value: Any,
    *,
    corpus: set[str],
    fallback: str,
) -> tuple[str, list[str]]:
    clean = re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()
    if not clean:
        return fallback, []
    kept: list[str] = []
    removed: list[str] = []
    for segment in [part.strip() for part in _TITLE_SEPARATORS.split(clean) if part.strip()]:
        tokens = _claim_tokens(segment)
        if tokens and tokens.issubset(corpus):
            kept.append(segment)
        else:
            removed.append(segment)
    return (" | ".join(kept) if kept else fallback), removed


def enforce_title_evidence_consistency(
    result: dict[str, Any],
    *,
    product_name: str | None,
    product_type: str | None,
    site_brand: str,
    approved_selling_points: dict[str, Any],
    structured_specs: dict[str, Any] | None,
) -> dict[str, Any]:
    """Remove unsupported SEO/H1 claim segments and decode HTML entities."""

    output = dict(result)
    seo = dict(output.get("seo") or {})
    fallback = _neutral_fallback(product_name, product_type)
    corpus = title_evidence_corpus(
        product_name=product_name,
        product_type=product_type,
        site_brand=site_brand,
        approved_selling_points=approved_selling_points,
        structured_specs=structured_specs,
    )
    removed: dict[str, list[str]] = {}
    for field in ("title", "h1"):
        clean, dropped = _supported_title(
            seo.get(field), corpus=corpus, fallback=fallback
        )
        seo[field] = clean
        if dropped:
            removed[field] = dropped
    output["seo"] = seo
    output["evidence_consistency"] = {
        "status": "sanitized" if removed else "passed",
        "removed_unsupported_title_segments": removed,
        "approved_selling_points_only": True,
    }
    return output
