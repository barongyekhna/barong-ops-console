"""跨 GEO+SEO 的只读查询。

**这个文件里不许出现 ``"geo"`` / ``"seo"`` 字面量。** 一切按 ``SOURCES`` 表
循环 —— 加第三个内容源应该只改那张表。测试会断言这一点。

照 ``content_links/link_graph.py::_live_articles`` 的写法(仓库里已有的跨
GEO+SEO 同形查询),但过滤条件不同:那边找**已上线**的,这边找**待人处理**的。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..k_series.product_knowledge.scope_shim import KScopeContext, apply_scope_filters
from .dto import to_article
from .sources import SOURCES, ContentSource, source_for

logger = logging.getLogger(__name__)

REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_APPROVED = "approved"


def _parents(db: Session, source: ContentSource) -> dict[Any, Any]:
    model = source.parent_model_fn()
    return {p.id: p for p in db.execute(select(model)).scalars()}


def _product_labels(db: Session, source: ContentSource, parent: Any) -> dict[str, str]:
    """GEO 的产品 SKU。**必须解析**——裸 UUID 对运营毫无意义,而
    ``POST /geo/items/{id}/review`` 现在就是返回裸 UUID(老坑)。"""
    if not source.resolves_product_labels or parent is None:
        return {}
    try:
        from ..geo_series.content.service import product_label_map

        return product_label_map(db, cluster=parent)
    except Exception:  # noqa: BLE001 - 标签是增益,取不到不该让整页打不开
        logger.exception("product label lookup failed")
        return {}


def list_articles(
    db: Session,
    *,
    scope: KScopeContext | None = None,
    review_status: str | None = None,
    source_key: str | None = None,
) -> list[dict[str, Any]]:
    """归一化的文章列表,按创建时间倒序。不出网。"""
    out: list[tuple[Any, dict[str, Any]]] = []
    for source in SOURCES:
        if source_key and source.key != source_key:
            continue
        model = source.item_model_fn()
        query = apply_scope_filters(select(model), model, scope)
        if review_status:
            query = query.where(model.review_status == review_status)
        parents = _parents(db, source)
        label_cache: dict[Any, dict[str, str]] = {}
        for item in db.execute(query).scalars():
            parent = parents.get(getattr(item, source.parent_fk, None))
            key = getattr(item, source.parent_fk, None)
            if key not in label_cache:
                label_cache[key] = _product_labels(db, source, parent)
            out.append(
                (
                    getattr(item, "created_at", None),
                    to_article(
                        item,
                        source=source,
                        parent=parent,
                        product_labels=label_cache[key],
                    ),
                )
            )
    # 时间可能为 None(老数据),排序键退化成空字符串而不是抛异常。
    out.sort(key=lambda row: (row[0].isoformat() if row[0] else ""), reverse=True)
    return [article for _created, article in out]


def review_queue(
    db: Session, *, scope: KScopeContext | None = None
) -> list[dict[str, Any]]:
    """待审队列。**有序且稳定** —— 浮窗「批准，下一篇 →」靠它连着过完,
    顺序每次刷新都变的话,人会以为自己漏了一篇。

    排序:先按来源(同一批一起看,脑子不用来回切),再按创建时间正序
    (先写的先审)。
    """
    pending = list_articles(db, scope=scope, review_status=REVIEW_STATUS_PENDING)
    order = {s.key: i for i, s in enumerate(SOURCES)}
    pending.sort(key=lambda a: (order.get(a["source"], 99), a["created_at"] or ""))
    return pending


def article_ref(
    db: Session, *, source_key: str, item_id: str, scope: KScopeContext | None = None
) -> tuple[Any, Any, ContentSource] | None:
    """(item, parent, source)。找不到返回 ``None``,由调用方转 404。"""
    source = source_for(source_key)
    model = source.item_model_fn()
    query = apply_scope_filters(select(model), model, scope).where(model.id == item_id)
    item = db.execute(query).scalars().first()
    if item is None:
        return None
    parent_id = getattr(item, source.parent_fk, None)
    parent = (
        db.get(source.parent_model_fn(), parent_id) if parent_id is not None else None
    )
    return item, parent, source


def article_detail(
    db: Session,
    *,
    source_key: str,
    item_id: str,
    scope: KScopeContext | None = None,
    permissions: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    ref = article_ref(db, source_key=source_key, item_id=item_id, scope=scope)
    if ref is None:
        return None
    item, parent, source = ref
    return to_article(
        item,
        source=source,
        parent=parent,
        product_labels=_product_labels(db, source, parent),
        permissions=permissions,
    )


def step_counts(db: Session, *, scope: KScopeContext | None = None) -> dict[str, int]:
    """四步导轨的角标。步 5 会在 ``workflow.py`` 里用它。"""
    articles = list_articles(db, scope=scope)
    return {
        "generated": len(articles),
        "pending_review": sum(
            1 for a in articles if a["review_status"] == REVIEW_STATUS_PENDING
        ),
        "approved_unpublished": sum(
            1
            for a in articles
            if a["review_status"] == REVIEW_STATUS_APPROVED and not a["wp_post_id"]
        ),
        "live": sum(1 for a in articles if a["wp_status"] == "publish"),
    }


__all__ = [
    "REVIEW_STATUS_APPROVED",
    "REVIEW_STATUS_PENDING",
    "article_detail",
    "article_ref",
    "list_articles",
    "review_queue",
    "step_counts",
]
