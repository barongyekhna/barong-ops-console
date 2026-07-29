"""Resolve a K product to the URL a buyer can actually open.

Rail 1 of GEO delivery: content names a product and links to it, so when an answer
engine cites the article the reader can reach the product page. That only works if
the link is the real, public permalink.

**The trap (found in live data 2026-07-29):** ``p_upload_jobs.external_url`` stores
the permalink *as of upload time*, and P deliberately creates products as drafts on
first push — so early rows for PSPE-001 hold ``?post_type=product&p=4148`` (the
draft-era ugly form) while only the latest holds
``/product/portable-camping-shower-kit/``. Linking the draft form would send buyers
to an ugly URL, and linking a product that is still a draft sends them to a 404.

So: prefer a pretty ``/product/…`` permalink; treat a query-string-only permalink as
"not publicly linkable" and let the publish gate block on it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...p_series.upload.models import PUploadJob

# A published Woo product resolves to /product/<slug>/; the draft-era permalink is
# a bare query string. Only the former is safe to put in front of a buyer.
_PRETTY_MARKER = "/product/"


def _is_public_permalink(url: str) -> bool:
    normalized = (url or "").strip()
    if not normalized.startswith(("http://", "https://")):
        return False
    if "?" in normalized and _PRETTY_MARKER not in normalized:
        # e.g. https://site/?post_type=product&p=4148 — draft-era, not linkable.
        return False
    return _PRETTY_MARKER in normalized


def latest_public_url(
    db: Session, product_ids: list[UUID]
) -> dict[str, str]:
    """{product_id: public permalink} for products that really are linkable.

    Products with no successful upload, or whose only known permalink is the
    draft-era query-string form, are simply absent from the result — callers treat
    that as "cannot link this product yet".
    """
    if not product_ids:
        return {}
    rows = db.execute(
        select(
            PUploadJob.product_id,
            PUploadJob.external_url,
            PUploadJob.finished_at,
            PUploadJob.created_at,
        )
        .where(
            PUploadJob.product_id.in_(product_ids),
            PUploadJob.status == "success",
            PUploadJob.external_url.is_not(None),
        )
        .order_by(PUploadJob.finished_at.desc(), PUploadJob.created_at.desc())
    ).all()

    resolved: dict[str, str] = {}
    for product_id, url, _finished, _created in rows:
        key = str(product_id)
        if key in resolved:
            continue  # rows are newest-first; the first public one wins
        if _is_public_permalink(str(url or "")):
            resolved[key] = str(url).strip()
    return resolved


def product_display_title(product: Any) -> str:
    """The exact H1 the buyer sees on the product page.

    P resolves the Woo product title as seo.h1 → seo.title → product_name_en →
    product_key (``p_series.upload.assemble._title_for_upload``). GEO must land on
    the same string: an article that names the product differently from its own PDP
    reads as a different product to both a buyer and an answer engine. Never fall
    back to the UUID — it leaked into live copy once (2026-07-29) and is meaningless
    to a reader.
    """
    marketing = getattr(product, "marketing_copy_json", None)
    seo = marketing.get("seo") if isinstance(marketing, dict) else None
    seo = seo if isinstance(seo, dict) else {}
    for candidate in (
        seo.get("h1"),
        seo.get("title"),
        getattr(product, "product_name_en", None),
        getattr(product, "name", None),
        getattr(product, "sku", None),
        getattr(product, "product_key", None),
    ):
        text = " ".join(str(candidate or "").split())
        if text:
            return text
    return ""


def product_label_map(products: list[Any]) -> dict[str, str]:
    """{every identifier content may cite → the product's public H1}."""
    labels: dict[str, str] = {}
    for product in products:
        title = product_display_title(product)
        if not title:
            continue
        for alias in (
            product.id,
            getattr(product, "product_key", None),
            getattr(product, "sku", None),
        ):
            alias_text = str(alias or "").strip()
            if alias_text:
                labels[alias_text] = title
    return labels


def product_link_map(
    db: Session, products: list[Any]
) -> tuple[dict[str, str], list[str]]:
    """Map every identifier content may cite → public URL, plus the unlinkable SKUs.

    Generated copy cites whatever identifier it was handed (``product_key`` today,
    sometimes the SKU), so every alias resolves to the same URL. The second return
    value is the list of products that have no public page yet — the publish gate
    turns those into blockers instead of shipping dead links.
    """
    ids = [p.id for p in products]
    by_id = latest_public_url(db, ids)
    links: dict[str, str] = {}
    unlinkable: list[str] = []
    for product in products:
        url = by_id.get(str(product.id))
        label = str(getattr(product, "sku", "") or product.id)
        if not url:
            unlinkable.append(label)
            continue
        links[str(product.id)] = url
        for alias in (
            getattr(product, "product_key", None),
            getattr(product, "sku", None),
        ):
            alias_text = str(alias or "").strip()
            if alias_text:
                links[alias_text] = url
    return links, unlinkable


__all__ = [
    "latest_public_url",
    "product_display_title",
    "product_label_map",
    "product_link_map",
]
