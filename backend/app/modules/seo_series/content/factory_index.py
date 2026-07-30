"""``/factory/`` 枢纽页——信任枢纽的门面。

和 ``/guides/`` 同一套做法(``content_core.wp_pages.upsert_page``,那个修好的
"只在 404 才重建、重建前先按 slug 认领"的版本),但内容组织方式不同:
指南按**谷歌类目**分组(买家按品类找),工艺文按**体裁**分组
(Craft & Process / Materials / Testing / Behind the Brand / Wholesale)——
来这一页的人问的不是"我要买什么",而是**"你们到底是谁、能不能做"**。
"""

from __future__ import annotations

import html as _html
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import constants as C
from .models import SeoContentItem
from .wp_terms import FACTORY_CATEGORIES

logger = logging.getLogger(__name__)

FACTORY_SLUG = "factory"
FACTORY_TITLE = "Inside the Factory"

_INTRO = (
    "We build what we sell. These pages document how — the processes, the "
    "materials, what we test and what the tests actually showed. They are here "
    "so you can check us, not so we can tell you we are good."
)


def render_factory_page(groups: list[tuple[str, list[dict[str, str]]]]) -> str:
    parts = [
        '<div class="barong-factory">',
        f"<p class=\"by-lead\">{_html.escape(_INTRO)}</p>",
    ]
    for heading, rows in groups:
        if not rows:
            continue
        items = "".join(
            f'<li><a href="{_html.escape(r["url"], quote=True)}">'
            f"{_html.escape(r['title'])}</a></li>"
            for r in rows
        )
        parts.append(
            f"<section><h2>{_html.escape(heading)}</h2><ul>{items}</ul></section>"
        )
    if len(parts) == 2:
        # 一篇都还没发布时,不要出一个空壳页面装作有内容。
        parts.append("<p>Documentation is being written. Check back soon.</p>")
    parts.append("</div>")
    return "".join(parts)


def factory_groups(db: Session) -> list[tuple[str, list[dict[str, str]]]]:
    """按体裁分组的**线上可见**文章。

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
    for rows_ in by_kind.values():
        rows_.sort(key=lambda r: r["title"])
    return [
        (heading, by_kind.get(kind, []))
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
