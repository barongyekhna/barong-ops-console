"""The Guides hub page — one front door for every published topic cluster.

Owner's ruling: guides get their own entry point rather than being scattered into
the blog feed, because a buying guide and a brand story serve different reader
intents. The hub doubles as the internal-link map an answer engine reads to see
the whole shape of what this site actually knows.

It is a normal WordPress **page**, created once and rewritten after each publish
so a new cluster appears without anyone maintaining a menu. It never touches the
site's existing structural pages (``page_on_front`` / ``page_for_posts``): it
finds its own page by the id stored in ``geo_site_settings``, and creates one only
when that id is absent or the page is gone.
"""

from __future__ import annotations

import logging
from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import GUIDES_PAGE_ID_KEY, GeoSiteSetting

logger = logging.getLogger(__name__)

GUIDES_PAGE_TITLE = "Buying Guides"
GUIDES_PAGE_SLUG = "guides"
_PAGES_PATH = "pages"


def _get_setting(db: Session, key: str) -> str | None:
    row = db.execute(
        select(GeoSiteSetting.value).where(GeoSiteSetting.key == key)
    ).scalar_one_or_none()
    return str(row) if row else None


def _set_setting(db: Session, key: str, value: str) -> None:
    existing = db.get(GeoSiteSetting, key)
    if existing is None:
        db.add(GeoSiteSetting(key=key, value=value))
    else:
        existing.value = value
    db.flush()


def render_index_html(groups: list[dict[str, Any]]) -> str:
    """Hub body: clusters grouped by their Google-taxonomy breadcrumb.

    Deterministic, escaped, stable ``geo-*`` classes — same rules as article HTML.
    """
    parts: list[str] = [
        '<div class="geo-index">',
        '<p class="geo-index-lead">',
        escape(
            "Practical buying guides written from the real specifications of the "
            "products we make — how these products work, how to choose, and what "
            "they are actually good for."
        ),
        "</p>",
    ]
    for group in groups:
        breadcrumb = str(group.get("category_path") or "").strip()
        clusters = group.get("clusters") or []
        if not clusters:
            continue
        parts.append('<section class="geo-index-group">')
        if breadcrumb:
            parts.append(f"<h2>{escape(breadcrumb)}</h2>")
        for cluster in clusters:
            title = str(cluster.get("title") or "").strip()
            if title:
                parts.append(f'<h3 class="geo-index-cluster">{escape(title)}</h3>')
            articles = cluster.get("articles") or []
            if not articles:
                continue
            rows = "".join(
                f'<li><a href="{escape(str(a.get("url") or ""))}">'
                f'{escape(str(a.get("title") or ""))}</a></li>'
                for a in articles
                if str(a.get("url") or "").strip()
            )
            if rows:
                parts.append(f"<ul>{rows}</ul>")
        parts.append("</section>")
    parts.append("</div>")
    return "".join(parts)


def collect_published_groups(db: Session) -> list[dict[str, Any]]:
    """Every cluster that has at least one live article, grouped by taxonomy."""
    from .models import GeoContentCluster, GeoContentItem

    rows = db.execute(
        select(
            GeoContentCluster.id,
            GeoContentCluster.title,
            GeoContentCluster.category_path,
            GeoContentItem.title,
            GeoContentItem.published_url,
            GeoContentItem.item_type,
        )
        .join(GeoContentItem, GeoContentItem.cluster_id == GeoContentCluster.id)
        .where(GeoContentItem.published_url.is_not(None))
        .order_by(GeoContentCluster.created_at, GeoContentItem.item_type)
    ).all()

    grouped: dict[str, dict[str, Any]] = {}
    for cluster_id, cluster_title, category_path, title, url, _item_type in rows:
        breadcrumb = str(category_path or "").strip() or "Guides"
        group = grouped.setdefault(
            breadcrumb, {"category_path": breadcrumb, "_by_cluster": {}}
        )
        cluster = group["_by_cluster"].setdefault(
            str(cluster_id), {"title": str(cluster_title or ""), "articles": []}
        )
        cluster["articles"].append({"title": str(title or ""), "url": str(url or "")})

    out: list[dict[str, Any]] = []
    for breadcrumb, group in grouped.items():
        out.append(
            {
                "category_path": breadcrumb,
                "clusters": list(group["_by_cluster"].values()),
            }
        )
    return out


def refresh_guides_index_safely(db: Session) -> str | None:
    """Create-or-update the hub page. Returns its URL, or None on any failure.

    Fail-open on purpose: the articles are already live and useful; a hub page
    that could not be refreshed is a cosmetic problem, never a publish failure.
    """
    try:
        return _refresh_guides_index(db)
    except Exception:  # noqa: BLE001 - the hub is a nicety, not a gate
        logger.exception("GEO guides index refresh failed")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("GEO guides index rollback failed")
        return None


def _refresh_guides_index(db: Session) -> str | None:
    from ....services import wp_bridge

    groups = collect_published_groups(db)
    if not groups:
        return None
    html = render_index_html(groups)
    page_id = _get_setting(db, GUIDES_PAGE_ID_KEY)
    # 死规矩: release the transaction before talking to WordPress.
    db.commit()

    credentials = wp_bridge._resolve_credentials(db=db)
    if credentials is None:
        logger.warning("GEO guides index skipped: WordPress credentials unavailable")
        return None

    payload = {
        "title": GUIDES_PAGE_TITLE,
        "slug": GUIDES_PAGE_SLUG,
        "content": html,
        "status": "publish",
    }

    if page_id:
        result = wp_bridge._request_json(
            wp_bridge._api_url(credentials, f"{_PAGES_PATH}/{page_id}"),
            credentials=credentials,
            authenticated=True,
            method="POST",
            payload=payload,
        )
        if result.get("reachable"):
            data = result.get("data") or {}
            return str(data.get("link") or "") or None
        logger.warning(
            "GEO guides index update failed (%s); recreating", result.get("error")
        )

    created = wp_bridge._request_json(
        wp_bridge._api_url(credentials, _PAGES_PATH),
        credentials=credentials,
        authenticated=True,
        method="POST",
        payload=payload,
    )
    if not created.get("reachable"):
        logger.warning("GEO guides index create failed: %s", created.get("error"))
        return None
    data = created.get("data") or {}
    new_id = data.get("id")
    if new_id:
        _set_setting(db, GUIDES_PAGE_ID_KEY, str(new_id))
        db.commit()
    return str(data.get("link") or "") or None


__all__ = [
    "GUIDES_PAGE_TITLE",
    "GUIDES_PAGE_SLUG",
    "render_index_html",
    "collect_published_groups",
    "refresh_guides_index_safely",
]
