"""Create-or-update a WordPress page, without ever leaving a duplicate behind.

**The bug this exists to kill** (found by the B2B session while copying
``geo_series/content/guides_index.py``, 2026-07-29): the original fell back to
"create a new page" on **any** unreachable result. A single WP timeout therefore
produced a second ``/guides/`` page, and the stored id was overwritten so the
first one became an orphan nobody could find again. The copy was more correct than
the original — which is exactly why this now lives in one place.

The rule, in order:

1. update by the stored id;
2. **only a genuine 404** (the page really is gone) justifies recovery — a timeout
   or a 500 aborts the run instead, because guessing "it must not exist" is how
   duplicates get made;
3. before creating anything, **claim by slug** — that recovers a page someone made
   by hand, or one whose id we lost.

Creating is the last resort, never the fallback.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

_PAGES_PATH = "pages"


class WpPageError(RuntimeError):
    """The page could not be written. The caller must not retry by creating."""


def _find_by_slug(credentials: Any, slug: str) -> int | None:
    """The id of an existing page with this slug, if any."""
    from ...services import wp_bridge

    # _request_json 不支持 params,查询串直接拼进 path(与 b2b 侧同口径)。
    query = urlencode({"slug": slug, "status": "any", "per_page": 1, "_fields": "id"})
    result = wp_bridge._request_json(  # noqa: SLF001
        wp_bridge._api_url(credentials, f"{_PAGES_PATH}?{query}"),
        credentials=credentials,
        authenticated=True,
    )
    if not result.get("reachable"):
        return None
    data = result.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        page_id = data[0].get("id")
        return int(page_id) if page_id else None
    return None


def upsert_page(
    credentials: Any,
    *,
    page_id: int | None,
    slug: str,
    title: str,
    content: str,
    parent: int | None = None,
    status: str = "publish",
) -> tuple[int | None, str | None]:
    """(page_id, link). Raises ``WpPageError`` rather than creating a duplicate."""
    from ...services import wp_bridge

    payload: dict[str, Any] = {
        "title": title,
        "slug": slug,
        "content": content,
        "status": status,
    }
    if parent:
        payload["parent"] = parent

    def _post(target: str) -> dict[str, Any]:
        return wp_bridge._request_json(  # noqa: SLF001
            wp_bridge._api_url(credentials, target),
            credentials=credentials,
            authenticated=True,
            method="POST",
            payload=payload,
        )

    if page_id:
        result = _post(f"{_PAGES_PATH}/{page_id}")
        if result.get("reachable"):
            data = result.get("data")
            return page_id, (data.get("link") if isinstance(data, dict) else None)
        if result.get("status") != 404:
            # Timeout or 5xx: abandon this run. NEVER create a second page here —
            # that is precisely the defect this module was extracted to fix.
            raise WpPageError(
                f"更新页面 {slug} 失败（{result.get('error')}），本次不改动。"
            )
        logger.warning("Page %s (%s) is gone; recovering by slug", page_id, slug)

    found = _find_by_slug(credentials, slug)
    if found:
        result = _post(f"{_PAGES_PATH}/{found}")
        if result.get("reachable"):
            data = result.get("data")
            return found, (data.get("link") if isinstance(data, dict) else None)
        raise WpPageError(f"更新页面 {slug} 失败（{result.get('error')}）。")

    created = _post(_PAGES_PATH)
    if not created.get("reachable"):
        raise WpPageError(f"创建页面 {slug} 失败（{created.get('error')}）。")
    data = created.get("data") or {}
    new_id = data.get("id")
    return (int(new_id) if new_id else None), data.get("link")


__all__ = ["WpPageError", "upsert_page"]
