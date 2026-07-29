"""Rail 2: the "Learn more" block a product page carries back to its guides.

One builder, two consumers — P injects the block while assembling an upload, and
the backlink workflow rewrites it on an already-live product. Both must emit a
byte-identical block or they would fight each other on every run, so the markup
lives here and nowhere else.

**Owner's hard rule: only the category's own guide articles may be linked, never
the /guides/ hub page.** A product page that points at the hub dumps the buyer into
an index of everything the site sells; the whole value of the return leg is landing
them on the article that answers *their* question. ``_is_hub_url`` enforces it, and
it is a filter rather than an assertion so one bad row can never block the run.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from .related_guides import published_guides_for_product_safely

logger = logging.getLogger(__name__)

# The block is marker-delimited so rewriting it on live HTML is a replace, never an
# append — that is the only thing that makes read-modify-write safe to repeat.
BLOCK_CLASS = "kp-guides"
BLOCK_HEADING = "Learn more"
_BLOCK_RE = re.compile(
    r'<section class="[^"]*\bkp-guides\b[^"]*">.*?</section>',
    re.IGNORECASE | re.DOTALL,
)

# Paths that are indexes, not answers. The hub lives at /guides/ (see
# guides_index.GUIDES_PAGE_SLUG); anything that resolves to it is never a target.
_INDEX_PATHS = {"", "/", "/guides", "/guides/"}


def _is_hub_url(url: str) -> bool:
    """True for the guides hub (or any bare index), which must never be linked."""
    try:
        path = urlparse(str(url or "").strip()).path or ""
    except ValueError:
        return True
    return path.rstrip("/").lower() in {p.rstrip("/") for p in _INDEX_PATHS}


def article_guides_only(guides: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Drop anything that is not a specific guide article (死命令: no hub link)."""
    kept: list[tuple[str, str]] = []
    for title, url in guides:
        if not str(title or "").strip() or not str(url or "").strip():
            continue
        if _is_hub_url(url):
            logger.warning("backlink: refusing to link the guides hub (%s)", url)
            continue
        kept.append((str(title).strip(), str(url).strip()))
    return kept


def build_guides_block(guides: list[tuple[str, str]]) -> str:
    """The block itself. Empty input yields an empty string — never an empty box."""
    safe = article_guides_only(guides)
    if not safe:
        return ""
    items = "".join(
        f'<li><a href="{html_lib.escape(url)}">{html_lib.escape(title)}</a></li>'
        for title, url in safe
    )
    return (
        f'<section class="kp-box {BLOCK_CLASS}"><h2>{BLOCK_HEADING}</h2>'
        f"<ul>{items}</ul></section>"
    )


def apply_guides_block(description_html: str, block: str) -> str:
    """Replace an existing block, else append before the closing wrapper.

    Idempotent by construction: running it a hundred times leaves exactly one block.
    An empty ``block`` removes the section, which is how a product whose guides were
    all unpublished gets cleaned up.
    """
    current = str(description_html or "")
    if _BLOCK_RE.search(current):
        return _BLOCK_RE.sub(lambda _m: block, current, count=1)
    if not block:
        return current
    closing = current.rfind("</div>")
    if closing < 0:
        return current + block
    return current[:closing] + block + current[closing:]


def guides_block_for_product(
    db: Session, *, product_id: Any, product_key: str | None = None
) -> str:
    """The block this product should carry right now ("" = it should carry none)."""
    return build_guides_block(
        published_guides_for_product_safely(
            db, product_id=product_id, product_key=product_key
        )
    )


__all__ = [
    "BLOCK_CLASS",
    "BLOCK_HEADING",
    "apply_guides_block",
    "article_guides_only",
    "build_guides_block",
    "guides_block_for_product",
]
