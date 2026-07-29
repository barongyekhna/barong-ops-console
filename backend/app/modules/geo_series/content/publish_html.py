"""Render one stored guide piece into the HTML WordPress will hold.

Deterministic assembly only — no AI here. The words were written (and reviewed)
upstream; this just lays them out and wires the links, the same division of labour
as ``p_series/upload/description_html.py``.

Two kinds of link, resolved differently:

* **product links** — the product page already exists, so its real permalink is
  written straight into the HTML (Rail 1: the reader can reach the product);
* **intra-cluster links** — the sibling posts do not exist yet, so they render as
  ``{{GEO_LINK_<item_id>}}`` placeholders that the publisher swaps for real URLs
  once every post has been created. Exactly the handshake P already uses for
  images (``{{KP_IMG_n}}``).

Markup uses stable ``geo-*`` classes and nothing else — styling lives in the site
stylesheet, never inline, so a restyle never means republishing.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any

_LINK_TOKEN = "{{GEO_LINK_%s}}"


def link_token(item_id: Any) -> str:
    return _LINK_TOKEN % str(item_id)


def _paragraph(text: str) -> str:
    return f'<p class="geo-p">{escape(text)}</p>'


def render_article_html(
    item: Any,
    *,
    product_links: dict[str, str],
    product_labels: dict[str, str] | None = None,
    cluster_product_ids: list[str] | None = None,
    sibling_links: list[tuple[str, Any]],
) -> str:
    """Body HTML for one guide piece.

    ``sibling_links`` is [(title, item_id)] for the other pieces in the cluster;
    they render as placeholder-linked list items.
    """
    body = item.body_json if isinstance(item.body_json, dict) else {}
    parts: list[str] = ['<div class="geo-article">']

    for section in body.get("sections") or []:
        if not isinstance(section, dict):
            continue
        heading = str(section.get("heading") or "").strip()
        text = str(section.get("body") or "").strip()
        if not heading and not text:
            continue
        parts.append('<section class="geo-section">')
        if heading:
            parts.append(f"<h2>{escape(heading)}</h2>")
        if text:
            parts.append(_paragraph(text))
        parts.append("</section>")

    blocks = [b for b in (body.get("answer_blocks") or []) if isinstance(b, dict)]
    if blocks:
        rows: list[str] = []
        for block in blocks:
            question = str(block.get("question") or "").strip()
            answer = str(block.get("answer") or "").strip()
            if not question or not answer:
                continue
            # Native <details> — zero JS, and wp_kses passes it (proven on the PDP).
            rows.append(
                '<details class="geo-faq-item">'
                f"<summary>{escape(question)}</summary>"
                f'<div class="geo-faq-a">{_paragraph(answer)}</div>'
                "</details>"
            )
        if rows:
            parts.append(
                '<section class="geo-faq"><h2>Frequently asked questions</h2>'
                + "".join(rows)
                + "</section>"
            )

    # Rail 1: the products this guide covers, as real links.
    referenced = _referenced_products(
        item, product_links, product_labels or {}, cluster_product_ids
    )
    if referenced:
        items = "".join(
            f'<li><a class="geo-product-link" href="{escape(url)}">{escape(label)}</a></li>'
            for label, url in referenced
        )
        heading = (
            "The product in this guide"
            if len(referenced) == 1
            else "The products in this guide"
        )
        parts.append(
            f'<section class="geo-products"><h2>{heading}</h2>'
            f"<ul>{items}</ul></section>"
        )

    if sibling_links:
        items = "".join(
            f'<li><a href="{link_token(sibling_id)}">{escape(title)}</a></li>'
            for title, sibling_id in sibling_links
        )
        parts.append(
            '<section class="geo-more"><h2>More in this guide</h2>'
            f"<ul>{items}</ul></section>"
        )

    parts.append("</div>")
    return "".join(parts)


def _referenced_products(
    item: Any,
    product_links: dict[str, str],
    product_labels: dict[str, str],
    cluster_product_ids: list[str] | None = None,
) -> list[tuple[str, str]]:
    """(label, url) for every product this guide covers and that is publicly live.

    **Driven by the cluster, not by the copy.** This block is pure data — a name and
    a link — so binding it to ``source_product_ids_json`` (frozen by the generator at
    write time) meant a product added to the category later never appeared, even
    though the guide is about that category. Rendering from the cluster's product
    list instead makes "new product joins an existing cluster" a one-step fix: hit
    publish again and the link is there — no regeneration, no re-approval, and not a
    word of approved copy touched.

    The label must be the product's public H1. It used to fall back to whatever
    identifier the copy cited, which put a raw UUID in front of readers in live
    content (2026-07-29 — that product's ``product_key`` is itself UUID-shaped). A
    product with no resolvable title is dropped rather than linked under a
    meaningless label.
    """
    raw = item.source_product_ids_json
    refs = [str(r).strip() for r in raw] if isinstance(raw, list) else []
    # The copy's own citations come first (that is what the text talks about), then
    # everything else in the cluster.
    for extra in cluster_product_ids or []:
        text = str(extra).strip()
        if text and text not in refs:
            refs.append(text)
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for ref in refs:
        url = product_links.get(ref)
        label = product_labels.get(ref, "").strip()
        if not url or not label or url in seen:
            continue
        seen.add(url)
        out.append((label, url))
    return out


def plain_text(item: Any) -> str:
    """Flat text fallback (excerpt/search), no markup."""
    body = item.body_json if isinstance(item.body_json, dict) else {}
    pieces: list[str] = []
    for section in body.get("sections") or []:
        if isinstance(section, dict):
            pieces.append(str(section.get("body") or "").strip())
    for block in body.get("answer_blocks") or []:
        if isinstance(block, dict):
            pieces.append(str(block.get("answer") or "").strip())
    return " ".join(p for p in pieces if p)[:5000]


def unresolved_link_tokens(html: str) -> list[str]:
    """Placeholders still present — the publisher must replace every one."""
    return re.findall(r"\{\{GEO_LINK_[^}]+\}\}", html or "")


def resolve_link_tokens(html: str, urls: dict[str, str]) -> str:
    """Swap ``{{GEO_LINK_<item_id>}}`` for real post URLs (publisher side)."""
    out = html or ""
    for item_id, url in urls.items():
        out = out.replace(link_token(item_id), url)
    return out


__all__ = [
    "link_token",
    "render_article_html",
    "plain_text",
    "unresolved_link_tokens",
    "resolve_link_tokens",
]
