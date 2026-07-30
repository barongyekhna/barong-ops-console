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
import re
from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import GUIDES_PAGE_ID_KEY, GeoSiteSetting

logger = logging.getLogger(__name__)

GUIDES_PAGE_TITLE = "Buying Guides"
GUIDES_PAGE_SLUG = "guides"
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_SLUG_DASHES = re.compile(r"-{2,}")


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


def category_slug(text: str) -> str:
    """A CSS/id-safe token for one category. Empty input never yields an empty id."""
    cleaned = _SLUG_STRIP.sub("-", str(text or "").casefold()).strip("-")
    cleaned = _SLUG_DASHES.sub("-", cleaned)
    return cleaned[:60] or "other"


def leaf_of(breadcrumb: str) -> str:
    """Last node of a ``A > B > C`` taxonomy path."""
    segments = [s.strip() for s in str(breadcrumb or "").split(">") if s.strip()]
    return segments[-1] if segments else ""


def top_of(breadcrumb: str) -> str:
    """First node of a ``A > B > C`` taxonomy path — the "big" category."""
    segments = [s.strip() for s in str(breadcrumb or "").split(">") if s.strip()]
    return segments[0] if segments else ""


_HUB_CSS = """
.geo-hub{--geo-line:rgba(128,128,128,.28);--geo-soft:rgba(128,128,128,.08);
 padding:clamp(18px,4vw,44px);box-sizing:border-box}
.geo-hub-hero{text-align:center;padding:8px 0 28px}
.geo-hub-hero h2{margin:0 0 8px;font-size:clamp(26px,4vw,38px);line-height:1.15}
.geo-hub-lead{margin:0 auto 22px;max-width:60ch;opacity:.75;font-size:15px;line-height:1.6}
.geo-hub-search{position:relative;max-width:560px;margin:0 auto}
.geo-hub-search input{width:100%;box-sizing:border-box;padding:14px 18px;font-size:16px;
 line-height:1.4;border:1px solid var(--geo-line);border-radius:999px;background:transparent;
 color:inherit}
.geo-hub-search input:focus{outline:none;border-color:currentColor}
.geo-hub-filter{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin:0 0 26px}
.geo-hub-chip{cursor:pointer;padding:7px 15px;border-radius:999px;border:1px solid var(--geo-line);
 font-size:14px;line-height:1.25;background:transparent;color:inherit;opacity:.62}
.geo-hub-chip:hover{opacity:.92}
.geo-hub-chip[aria-pressed="true"]{opacity:1;font-weight:600;background:var(--geo-soft)}
.geo-hub-grid{display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.geo-hub-card{border:1px solid var(--geo-line);border-radius:14px;padding:20px 22px}
.geo-hub-card h3{margin:0 0 2px;font-size:19px;line-height:1.3}
.geo-hub-count{font-size:13px;opacity:.6}
.geo-hub-leaf{margin:14px 0 0;border-top:1px solid var(--geo-line);padding-top:12px}
.geo-hub-leaf:first-of-type{border-top:0;padding-top:4px}
.geo-hub-leaf>summary{cursor:pointer;list-style:none;display:flex;align-items:baseline;
 gap:8px;font-size:15px;line-height:1.35;opacity:.9}
.geo-hub-leaf>summary::-webkit-details-marker{display:none}
.geo-hub-leaf>summary::before{content:"+";font-size:15px;line-height:1;opacity:.55;
 width:1em;flex:none}
.geo-hub-leaf[open]>summary::before{content:"−"}
.geo-hub-leaf>summary:hover{opacity:1}
.geo-hub-leaf>summary h4{display:inline;margin:0;font-size:15px;font-weight:600;
 line-height:1.35}
.geo-hub-leaf-n{margin-left:auto;font-size:12px;opacity:.55;flex:none}
.geo-hub-cluster{margin:0 0 4px;font-size:12px;letter-spacing:.04em;text-transform:uppercase;
 opacity:.55}
.geo-hub-card ul{margin:0 0 6px;padding-left:18px}
.geo-hub-card li{margin:5px 0;line-height:1.45}
.geo-hub-empty{display:none;text-align:center;opacity:.7;padding:28px 0}
.geo-hub.is-empty .geo-hub-empty{display:block}
.geo-hub [hidden]{display:none !important}
@media (max-width:640px){.geo-hub-grid{grid-template-columns:1fr}}
"""

# Progressive enhancement: with JS off every guide is already visible, so the hub
# degrades to a plain linked index instead of an empty page.
_HUB_JS = """
(function(){
 var root=document.querySelector('.geo-hub');if(!root)return;
 var q=root.querySelector('.geo-hub-search input');
 var chips=[].slice.call(root.querySelectorAll('.geo-hub-chip'));
 var cards=[].slice.call(root.querySelectorAll('.geo-hub-card'));
 var top='all';
 function norm(s){return (s||'').toLowerCase();}
 function apply(){
  var term=norm(q&&q.value).trim();
  var anyCard=false;
  cards.forEach(function(card){
   var okTop=(top==='all'||card.getAttribute('data-top')===top);
   var anyLeaf=false;
   [].slice.call(card.querySelectorAll('.geo-hub-leaf')).forEach(function(leaf){
    var anyLink=false;
    [].slice.call(leaf.querySelectorAll('li')).forEach(function(li){
     var hay=norm(li.getAttribute('data-search'));
     var hit=!term||hay.indexOf(term)>-1;
     li.hidden=!hit;if(hit)anyLink=true;
    });
    leaf.hidden=!anyLink;if(anyLink)anyLeaf=true;
    // 搜索时自动展开命中的分组,否则结果藏在折叠里等于搜不到;
    // 清空搜索后恢复用户自己的展开状态。
    if(term){if(anyLink){if(!leaf.open){leaf.dataset.geoAuto='1';leaf.open=true;}}}
    else if(leaf.dataset.geoAuto==='1'){leaf.open=false;delete leaf.dataset.geoAuto;}
   });
   var show=okTop&&anyLeaf;
   card.hidden=!show;if(show)anyCard=true;
  });
  root.classList.toggle('is-empty',!anyCard);
 }
 chips.forEach(function(chip){
  chip.addEventListener('click',function(){
   top=chip.getAttribute('data-top')||'all';
   chips.forEach(function(c){c.setAttribute('aria-pressed',String(c===chip));});
   apply();
  });
 });
 if(q){q.addEventListener('input',apply);}
 apply();
})();
"""


def render_index_html(groups: list[dict[str, Any]]) -> str:
    """The Guides hub: search box, big-category chips, then one card per big category.

    Shaped after how help centres actually solve this (Google/Shopify): a prominent
    search first, then top-level categories as cards with their leaves nested inside.
    The point is that it must not read as "a site about one category" — so the body
    shows the **big** category and the **leaf**, never the whole
    ``A > B > C > D > E`` breadcrumb, and the layout grows as categories multiply.
    """
    usable = [g for g in groups if (g.get("clusters") or [])]

    # big category → [(leaf, clusters)]
    cards: dict[str, dict[str, Any]] = {}
    for group in usable:
        breadcrumb = str(group.get("category_path") or "").strip()
        top = top_of(breadcrumb) or "Guides"
        leaf = leaf_of(breadcrumb) or top
        card = cards.setdefault(top, {"title": top, "leaves": [], "count": 0})
        clusters = group.get("clusters") or []
        articles = sum(len(c.get("articles") or []) for c in clusters)
        card["leaves"].append({"leaf": leaf, "clusters": clusters})
        card["count"] += articles

    slugs: dict[str, str] = {}
    seen: set[str] = set()
    for top in cards:
        base = category_slug(top)
        slug, n = base, 2
        while slug in seen:
            slug, n = f"{base}-{n}", n + 1
        seen.add(slug)
        slugs[top] = slug

    parts: list[str] = [
        '<div class="geo-hub">',
        f"<style>{_HUB_CSS}</style>",
        '<header class="geo-hub-hero">',
        f"<h2>{escape(GUIDES_PAGE_TITLE)}</h2>",
        '<p class="geo-hub-lead">'
        + escape(
            "Practical guides written from the real specifications of the products "
            "we make — how they work, how to choose, and what they are actually "
            "good for."
        )
        + "</p>",
        '<div class="geo-hub-search">'
        '<input type="search" autocomplete="off" '
        'aria-label="Search guides" '
        'placeholder="Search guides — e.g. how long does the battery last">'
        "</div>",
        "</header>",
    ]

    if len(cards) > 1:
        parts.append('<nav class="geo-hub-filter" aria-label="Filter by category">')
        parts.append(
            '<button type="button" class="geo-hub-chip" data-top="all" '
            'aria-pressed="true">All guides</button>'
        )
        for top in cards:
            parts.append(
                f'<button type="button" class="geo-hub-chip" data-top="{slugs[top]}" '
                f'aria-pressed="false">{escape(top)}</button>'
            )
        parts.append("</nav>")

    parts.append('<div class="geo-hub-grid">')
    for top, card in cards.items():
        count = card["count"]
        parts.append(f'<section class="geo-hub-card" data-top="{slugs[top]}">')
        parts.append(f"<h3>{escape(top)}</h3>")
        parts.append(
            f'<div class="geo-hub-count">{count} guide{"s" if count != 1 else ""}</div>'
        )
        for leaf_group in card["leaves"]:
            leaf_count = sum(
                len(c.get("articles") or []) for c in leaf_group["clusters"]
            )
            # <details> keeps the hub short as categories pile up, and needs no JS —
            # with scripting off it is still a working expander.
            parts.append('<details class="geo-hub-leaf">')
            parts.append(
                "<summary>"
                f'<h4>{escape(str(leaf_group["leaf"]))}</h4>'
                f'<span class="geo-hub-leaf-n">{leaf_count}</span>'
                "</summary>"
            )
            for cluster in leaf_group["clusters"]:
                cluster_title = str(cluster.get("title") or "").strip()
                rows = []
                for article in cluster.get("articles") or []:
                    url = str(article.get("url") or "").strip()
                    title = str(article.get("title") or "").strip()
                    if not url or not title:
                        continue
                    haystack = " ".join(
                        [title, cluster_title, str(leaf_group["leaf"]), top]
                    ).casefold()
                    rows.append(
                        f'<li data-search="{escape(haystack)}">'
                        f'<a href="{escape(url)}">{escape(title)}</a></li>'
                    )
                if not rows:
                    continue
                if cluster_title:
                    parts.append(
                        f'<p class="geo-hub-cluster">{escape(cluster_title)}</p>'
                    )
                parts.append("<ul>" + "".join(rows) + "</ul>")
            parts.append("</details>")
        parts.append("</section>")
    parts.append("</div>")

    parts.append(
        '<p class="geo-hub-empty">'
        + escape("No guides match that search yet.")
        + "</p>"
    )
    parts.append(f"<script>{_HUB_JS}</script>")
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

    # 页面写入交给共享的 upsert：先按 id 更新 → 只有真 404 才认领/重建 →
    # 超时或 5xx 一律放弃本次。原来这里是"任何失败都新建"，WP 抖一下就多出
    # 一个重复 /guides/ 页、旧页变孤儿（b2b 照抄时发现并修正，现已下沉共享）。
    from ...content_core.wp_pages import WpPageError, upsert_page

    try:
        new_id, link = upsert_page(
            credentials,
            page_id=int(page_id) if page_id else None,
            slug=GUIDES_PAGE_SLUG,
            title=GUIDES_PAGE_TITLE,
            content=html,
        )
    except WpPageError as exc:
        logger.warning("GEO guides index write failed: %s", exc)
        return None

    if new_id and str(new_id) != str(page_id or ""):
        _set_setting(db, GUIDES_PAGE_ID_KEY, str(new_id))
        db.commit()
    return str(link or "") or None


__all__ = [
    "GUIDES_PAGE_TITLE",
    "GUIDES_PAGE_SLUG",
    "category_slug",
    "leaf_of",
    "top_of",
    "render_index_html",
    "collect_published_groups",
    "refresh_guides_index_safely",
]
