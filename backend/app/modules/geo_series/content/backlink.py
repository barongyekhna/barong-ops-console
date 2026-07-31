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

import logging
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ...content_core.html_blocks import apply_block, block_pattern, build_link_block
from .related_guides import published_guides_for_product_safely

logger = logging.getLogger(__name__)

# 定界块的机制本身已下沉 content_core/html_blocks.py(加了 kp-factory 之后有两个
# class、三个写入方,下沉判据成立)。这里只留 GEO 自己的常量和业务规矩。
BLOCK_CLASS = "kp-guides"
BLOCK_HEADING = "Learn more"
_BLOCK_RE = block_pattern(BLOCK_CLASS)

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
    """The block itself. Empty input yields an empty string — never an empty box.

    GEO 专属的那一层是 ``article_guides_only``(绝不链 /guides/ 枢纽页);拼装本身
    已下沉。
    """
    return build_link_block(
        block_class=BLOCK_CLASS,
        heading=BLOCK_HEADING,
        links=article_guides_only(guides),
    )


def apply_guides_block(description_html: str, block: str) -> str:
    """Replace an existing block, else append before the closing wrapper.

    Idempotent by construction: running it a hundred times leaves exactly one block.
    An empty ``block`` removes the section, which is how a product whose guides were
    all unpublished gets cleaned up.
    """
    return apply_block(description_html, block, block_class=BLOCK_CLASS)


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
