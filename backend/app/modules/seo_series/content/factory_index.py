"""``/factory/`` 枢纽页——信任枢纽的门面。

和 ``/guides/`` 同一套做法(``content_core.wp_pages.upsert_page``,那个修好的
"只在 404 才重建、重建前先按 slug 认领"的版本),但内容组织方式不同:
指南按**谷歌类目**分组(买家按品类找),工艺文按**体裁**分组
(Craft & Process / Materials / Testing / Behind the Brand / Wholesale)——
来这一页的人问的不是"我要买什么",而是**"你们到底是谁、能不能做"**。
"""

from __future__ import annotations

import logging
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import constants as C
from .models import SeoContentItem
from .wp_terms import FACTORY_CATEGORIES

logger = logging.getLogger(__name__)

FACTORY_SLUG = "factory"
FACTORY_TITLE = "Inside the Factory"

_LEAD = (
    "We build what we sell. These pages document how — the processes, the "
    "materials, what we test and what the tests actually showed. They are here "
    "so you can check us, not so we can tell you we are good."
)

# 每个分区一句话，说清楚"这一栏为什么值得点"。只给标题的分区读者不会点。
_SECTION_BLURB = {
    C.ITEM_CRAFT_STORY: "How a part is actually made, and why we chose that way.",
    C.ITEM_MATERIAL_EXPLAINER: "What each material buys you — and what it costs.",
    C.ITEM_TESTING: "What we test, how we test it, and the numbers that came back.",
    C.ITEM_BRAND_STORY: "Who we are, and why this factory exists.",
    C.ITEM_WHOLESALE_GUIDE: "Buying for a store: minimums, lead times, terms.",
}

# 和 /guides/ 同一套皮肤,只是分组维度不同(那边按品类,这边按体裁)——
# 来这一页的人问的不是"我要买什么",是"你们到底是谁、能不能做"。
_HUB_CSS = """
.by-fac{--by-line:rgba(0,0,0,.10);--by-dim:rgba(0,0,0,.62);max-width:1080px;margin:0 auto}
.by-fac-hero{padding:8px 0 18px;border-bottom:1px solid var(--by-line);margin-bottom:22px}
.by-fac-hero h2{margin:0 0 8px;font-size:30px;line-height:1.2}
.by-fac-lead{margin:0 0 16px;max-width:60ch;color:var(--by-dim);line-height:1.6}
.by-fac-search input{width:100%;max-width:520px;padding:11px 14px;font-size:15px;
 border:1px solid var(--by-line);border-radius:8px;background:#fff}
.by-fac-search input:focus{outline:2px solid rgba(0,0,0,.18);outline-offset:1px}
.by-fac-filter{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 20px}
.by-fac-chip{border:1px solid var(--by-line);background:#fff;border-radius:999px;
 padding:6px 14px;font-size:13px;cursor:pointer;line-height:1.3}
.by-fac-chip[aria-pressed="true"]{background:#111;color:#fff;border-color:#111}
.by-fac-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}
.by-fac-card{border:1px solid var(--by-line);border-radius:12px;padding:18px 18px 12px;
 background:#fff}
.by-fac-card h3{margin:0 0 4px;font-size:18px;line-height:1.3}
.by-fac-blurb{margin:0 0 10px;font-size:13px;color:var(--by-dim);line-height:1.5}
.by-fac-count{font-size:12px;letter-spacing:.04em;text-transform:uppercase;
 opacity:.55;margin-bottom:10px}
.by-fac-card ul{margin:0 0 8px;padding-left:18px}
.by-fac-card li{margin:6px 0;line-height:1.45}
.by-fac-soon{margin:0 0 8px;font-size:13px;color:var(--by-dim);font-style:italic}
.by-fac-empty{display:none;text-align:center;opacity:.7;padding:28px 0}
.by-fac.is-empty .by-fac-empty{display:block}
.by-fac [hidden]{display:none !important}
@media (max-width:640px){.by-fac-grid{grid-template-columns:1fr}}
"""

# 渐进增强:关掉 JS 每篇文章依然可见,退化成一个普通的链接目录。
_HUB_JS = """
(function(){
 var root=document.querySelector('.by-fac');if(!root)return;
 var q=root.querySelector('.by-fac-search input');
 var chips=[].slice.call(root.querySelectorAll('.by-fac-chip'));
 var cards=[].slice.call(root.querySelectorAll('.by-fac-card'));
 var kind='all';
 function norm(s){return (s||'').toLowerCase();}
 function apply(){
  var term=norm(q&&q.value).trim();var any=false;
  cards.forEach(function(card){
   var okKind=(kind==='all'||card.getAttribute('data-kind')===kind);
   var hitAny=false;
   [].slice.call(card.querySelectorAll('li')).forEach(function(li){
    var hit=!term||norm(li.getAttribute('data-search')).indexOf(term)>-1;
    li.hidden=!hit;if(hit)hitAny=true;
   });
   // 搜索时空分区直接收起来,否则一屏全是"暂无内容"
   var show=okKind&&(term?hitAny:true);
   card.hidden=!show;if(show)any=true;
  });
  root.classList.toggle('is-empty',!any);
 }
 chips.forEach(function(chip){chip.addEventListener('click',function(){
  kind=chip.getAttribute('data-kind')||'all';
  chips.forEach(function(c){c.setAttribute('aria-pressed',String(c===chip));});
  apply();});});
 if(q){q.addEventListener('input',apply);}
 apply();
})();
"""


def render_factory_page(groups: list[tuple[str, str, list[dict[str, str]]]]) -> str:
    """(体裁key, 标题, 文章列表) → 页面 HTML。

    与 /guides/ 同规:搜索框在最前、分区做成卡片。不同的是**分组维度**——
    指南按品类分(买家按品类找),工艺按体裁分(来的人问的是"你们是谁")。

    **空分区照样显示**,写一句"还在写"。理由:这一页的作用是让人一眼看到
    我们**打算证明哪几件事**;藏起来只会让页面看着像什么都没有。
    """
    total = sum(len(rows) for _k, _t, rows in groups)
    parts: list[str] = [
        '<div class="by-fac">',
        f"<style>{_HUB_CSS}</style>",
        '<header class="by-fac-hero">',
        f"<h2>{escape(FACTORY_TITLE)}</h2>",
        f'<p class="by-fac-lead">{escape(_LEAD)}</p>',
        '<div class="by-fac-search">'
        '<input type="search" autocomplete="off" aria-label="Search factory pages" '
        'placeholder="Search — e.g. waterproof seal, drop test, minimum order">'
        "</div>",
        "</header>",
        '<nav class="by-fac-filter" aria-label="Filter by topic">',
        '<button type="button" class="by-fac-chip" data-kind="all" '
        'aria-pressed="true">Everything</button>',
    ]
    for kind, heading, _rows in groups:
        parts.append(
            f'<button type="button" class="by-fac-chip" data-kind="{escape(kind)}" '
            f'aria-pressed="false">{escape(heading)}</button>'
        )
    parts.append("</nav>")

    parts.append('<div class="by-fac-grid">')
    for kind, heading, rows in groups:
        parts.append(f'<section class="by-fac-card" data-kind="{escape(kind)}">')
        parts.append(f"<h3>{escape(heading)}</h3>")
        blurb = _SECTION_BLURB.get(kind, "")
        if blurb:
            parts.append(f'<p class="by-fac-blurb">{escape(blurb)}</p>')
        if rows:
            label = "page" if len(rows) == 1 else "pages"
            parts.append(f'<div class="by-fac-count">{len(rows)} {label}</div>')
            items = []
            for row in rows:
                haystack = f"{row['title']} {heading} {blurb}".casefold()
                items.append(
                    f'<li data-search="{escape(haystack)}">'
                    f'<a href="{escape(row["url"], quote=True)}">'
                    f"{escape(row['title'])}</a></li>"
                )
            parts.append("<ul>" + "".join(items) + "</ul>")
        else:
            parts.append('<p class="by-fac-soon">Being written.</p>')
        parts.append("</section>")
    parts.append("</div>")
    parts.append('<p class="by-fac-empty">Nothing matches that search.</p>')
    if total == 0:
        parts.append(
            '<p class="by-fac-lead" style="margin-top:20px">'
            + escape(
                "Documentation is being written. Each section above is a claim we "
                "intend to back with evidence, not adjectives."
            )
            + "</p>"
        )
    parts.append(f"<script>{_HUB_JS}</script>")
    parts.append("</div>")
    return "".join(parts)


def factory_groups(db: Session) -> list[tuple[str, str, list[dict[str, str]]]]:
    """按体裁分组的**线上可见**文章 (体裁key, 标题, 文章)。

    死规矩:只认 ``wp_status == 'publish'``——首推刻意落草稿,
    published_url 那时就已写库,不查真实状态就会把草稿列进枢纽页。
    """
    rows = db.execute(
        select(
            SeoContentItem.item_kind,
            SeoContentItem.title,
            SeoContentItem.published_url,
        ).where(
            SeoContentItem.destination == C.DESTINATION_FACTORY,
            SeoContentItem.review_status == "approved",
            SeoContentItem.wp_status == "publish",
            SeoContentItem.published_url.is_not(None),
        )
    ).all()
    by_kind: dict[str, list[dict[str, str]]] = {}
    for kind, title, url in rows:
        if not str(url or "").strip():
            continue
        by_kind.setdefault(str(kind), []).append(
            {"title": str(title).strip(), "url": str(url).strip()}
        )
    for items in by_kind.values():
        items.sort(key=lambda r: r["title"])
    return [
        (kind, heading, by_kind.get(kind, []))
        for kind, heading in FACTORY_CATEGORIES.items()
    ]


def upsert_factory_index(db: Session, *, page_id: int | None = None) -> tuple[int, str]:
    """建/更新 /factory/ 页。返回 (page_id, url)。"""
    from ...content_core.wp_pages import upsert_page
    from ....services import wp_bridge

    html = render_factory_page(factory_groups(db))
    db.commit()  # 出网前放掉事务
    credentials = wp_bridge._resolve_credentials(db=db)  # noqa: SLF001
    if credentials is None:
        raise RuntimeError("WordPress 凭据不可用。")
    return upsert_page(
        credentials,
        slug=FACTORY_SLUG,
        title=FACTORY_TITLE,
        content=html,
        page_id=page_id,
    )


__all__ = [
    "FACTORY_SLUG",
    "FACTORY_TITLE",
    "factory_groups",
    "render_factory_page",
    "upsert_factory_index",
]
