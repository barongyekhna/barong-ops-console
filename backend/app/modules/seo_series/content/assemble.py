"""把已批准的 SEO 文章拼成发布包(n8n 取走的那份 JSON)。

契约与 GEO 的 ``geo-publish-package-v1`` **同形**——同一条 n8n 结构读两种包,
字段名必须一致,否则通用生成器就白抽了。
"""

from __future__ import annotations

import html as _html
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ...content_core.publish_html import link_token, plain_text
from .links import links_block_html, resolve_link_intents
from .models import SeoContentItem, SeoTopic

# 契约版本号住在 constants:n8n 的 builder 要读它,而 builder 不该为了一个
# 字符串把整棵 models 依赖树拉进来(会撞循环导入)。
from .constants import SEO_PUBLISH_PACKAGE_VERSION


def _sections_html(item: SeoContentItem) -> str:
    body = item.body_json if isinstance(item.body_json, dict) else {}
    parts: list[str] = []
    for section in body.get("sections") or []:
        if not isinstance(section, dict):
            continue
        heading = str(section.get("heading") or "").strip()
        text = str(section.get("body") or "").strip()
        if heading:
            parts.append(f"<h2>{_html.escape(heading)}</h2>")
        if text:
            parts.append(f"<p>{_html.escape(text)}</p>")
    return "".join(parts)


def render_article_html(db: Session, item: SeoContentItem, topic: SeoTopic) -> tuple[str, list[str]]:
    """(HTML, 没解析出来的内链说明)。"""
    links_json = item.links_json if isinstance(item.links_json, dict) else {}
    links, unresolved = resolve_link_intents(
        db,
        intents=links_json.get("intents") or [],
        category_id=topic.google_category_id,
    )
    return _sections_html(item) + links_block_html(links), unresolved


def assemble_seo_package(
    db: Session,
    *,
    items: list[SeoContentItem],
    job_id: str | None = None,
) -> dict[str, Any]:
    from .wp_terms import ensure_category

    articles: list[dict[str, Any]] = []
    notes: list[str] = []
    category_ids: set[int] = set()

    for item in items:
        topic = db.get(SeoTopic, item.topic_id)
        html, unresolved = render_article_html(db, item, topic)
        notes.extend(unresolved)
        term_id = ensure_category(
            db, item_kind=item.item_kind, destination=item.destination
        )
        category_ids.add(term_id)
        seo_raw = item.seo_json if isinstance(item.seo_json, dict) else {}
        articles.append(
            {
                "item_id": str(item.id),
                "item_type": item.item_kind,
                "title": str(item.title),
                "html": html,
                "text": plain_text(item),
                "seo": {
                    "title": str(seo_raw.get("title") or "").strip() or None,
                    "meta_description": (
                        str(seo_raw.get("meta_description") or "").strip() or None
                    ),
                    # 二道锁:发布过的文章干脆不下发 slug,让 WP 保持现有固定链接。
                    "url_slug": (
                        None
                        if item.wp_post_id
                        else (str(seo_raw.get("url_slug") or "").strip() or None)
                    ),
                },
                "wp_existing_post_id": item.wp_post_id,
                "link_token": link_token(item.id),
                # 每篇自己的分类:一个包里可能混着 factory 文和博文。
                "wp_category_id": term_id,
            }
        )

    return {
        "schema_version": SEO_PUBLISH_PACKAGE_VERSION,
        "job_id": job_id,
        "channel": "wordpress",
        "generated_at": datetime.now(UTC).isoformat(),
        "articles": articles,
        # 包级也带一个,给通用 n8n 结构的兜底门禁用(它只认这一个字段)。
        "wp_category_id": sorted(category_ids)[0] if category_ids else None,
        "notes": notes,
    }


__all__ = [
    "SEO_PUBLISH_PACKAGE_VERSION",
    "assemble_seo_package",
    "render_article_html",
]
