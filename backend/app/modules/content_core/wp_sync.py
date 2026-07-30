"""Make the database tell the truth about what is actually live on WordPress.

**The bug this exists to kill** (spotted by the B2B session, 2026-07-29): a
``published_url`` in our tables only means "we once wrote this to WP". It does not
mean a visitor can see it. The publisher deliberately creates posts as ``draft`` on
first push and waits for a human to hit publish — and the URL is written at that
first push. When the operator later publishes in WP, the console never finds out.

Every consumer of that column therefore risks linking to a draft: the product-page
"Learn more" block, the wholesale pages' guide lists, and any future content area.
Fixing it in each consumer means each one pays for its own WP round trip — and the
B2B call site loops per product, so that would be N requests.

So the fix is here, at the source: **one batch call refreshes the真实 status for
many posts at once**, writes it back, and every consumer just reads the column.
The canonical ``link`` WP returns also overwrites any historical ``?p=<id>`` URL
left over from the draft era.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# WP caps `include` lists; stay well inside it and page through.
_BATCH = 50
_POSTS_PATH = "posts"


def fetch_post_states(
    credentials: Any, post_ids: list[int]
) -> dict[int, dict[str, str]]:
    """{post_id: {"status", "link"}} straight from WordPress. Missing ids are absent."""
    from ...services import wp_bridge

    wanted = sorted({int(p) for p in post_ids if p})
    out: dict[int, dict[str, str]] = {}
    for start in range(0, len(wanted), _BATCH):
        chunk = wanted[start : start + _BATCH]
        query = urlencode(
            {
                "include": ",".join(str(p) for p in chunk),
                "status": "any",
                "per_page": len(chunk),
                "_fields": "id,status,link",
            }
        )
        result = wp_bridge._request_json(  # noqa: SLF001
            wp_bridge._api_url(credentials, f"{_POSTS_PATH}?{query}"),
            credentials=credentials,
            authenticated=True,
        )
        if not result.get("reachable"):
            logger.warning("WP post-state refresh failed: %s", result.get("error"))
            continue
        for row in result.get("data") or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            out[int(row["id"])] = {
                "status": str(row.get("status") or ""),
                "link": str(row.get("link") or ""),
            }
    return out


__all__ = ["fetch_post_states"]
