"""统一发布动作。

**操作的是「发布单元」,不是文章。** GEO 一次发整簇、SEO 一次发选中的几篇。
做成「每篇一个发布按钮」必然骗人:点 GEO 一篇,同簇另外三篇会跟着出去,
而界面上什么都没说。

所以先给 preview —— **逐篇列出这次到底会发哪几篇**,再让人点。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..k_series.product_knowledge.scope_shim import KScopeContext, apply_scope_filters
from .queries import REVIEW_STATUS_APPROVED
from .sources import SOURCES, ContentSource

logger = logging.getLogger(__name__)


def _public_base() -> str:
    return os.getenv("PUBLIC_API_BASE_URL", "").strip()


def _approved(db: Session, source: ContentSource, scope: KScopeContext | None) -> list[Any]:
    """已批准但还没上线的。"""
    model = source.item_model_fn()
    query = apply_scope_filters(select(model), model, scope).where(
        model.review_status == REVIEW_STATUS_APPROVED,
        model.wp_post_id.is_(None),
    )
    return list(db.execute(query).scalars())


def preview(db: Session, *, scope: KScopeContext | None = None) -> list[dict[str, Any]]:
    """每个发布单元:会发哪几篇、被什么挡着。不出网。"""
    units: list[dict[str, Any]] = []
    for source in SOURCES:
        items = _approved(db, source, scope)
        if not items:
            continue
        if source.publish_unit == "parent":
            # 按父记录分组——GEO 的一单就是一个簇。
            groups: dict[Any, list[Any]] = {}
            for item in items:
                groups.setdefault(getattr(item, source.parent_fk), []).append(item)
            parents = {p.id: p for p in db.execute(select(source.parent_model_fn())).scalars()}
            for parent_id, group in groups.items():
                parent = parents.get(parent_id)
                units.append(
                    {
                        "source": source.key,
                        "unit_id": str(parent_id),
                        "label": str(
                            getattr(parent, source.parent_label_column, "") or "（无名簇）"
                        ),
                        "titles": [str(i.title) for i in group],
                        "blockers": _blockers(
                            db, source, parent=parent, items=group, scope=scope
                        ),
                    }
                )
        else:
            units.append(
                {
                    "source": source.key,
                    # SEO 一单 = 这一批 item_ids,没有父记录,unit_id 用来源 key。
                    "unit_id": source.key,
                    "label": source.label,
                    "titles": [str(i.title) for i in items],
                    "blockers": _blockers(
                        db, source, parent=None, items=items, scope=scope
                    ),
                }
            )
    return units


def _blockers(
    db: Session,
    source: ContentSource,
    *,
    parent: Any,
    items: list[Any],
    scope: KScopeContext | None,
) -> list[str]:
    try:
        if source.publish_unit == "parent":
            from ..geo_series.content.assemble import cluster_products
            from ..geo_series.content.publish_gate import (
                publish_blockers as geo_blockers,
            )

            products = cluster_products(db, cluster=parent, scope_context=scope)
            return geo_blockers(db, cluster=parent, items=items, products=products)
        from ..seo_series.content.publish_gate import publish_blockers as seo_blockers

        return seo_blockers(db, item_ids=[i.id for i in items])
    except Exception as exc:  # noqa: BLE001 - 算不出来就如实说,别假装能发
        logger.exception("publish blockers failed")
        return [f"发布前检查暂时算不出来：{str(exc)[:80]}"]


def dispatch(
    db: Session,
    *,
    source: ContentSource,
    unit_id: str,
    scope: KScopeContext,
    user: Any,
) -> dict[str, Any]:
    """派一单。**调用后必须再 commit** —— ``create_publish_job`` 只在真的派出去
    的时候内部 commit,「队列里已有在飞」时什么都不派也不 commit,新建的 job 行
    就只 flush 过。
    """
    if source.publish_unit == "parent":
        from ..geo_series.content.publish_jobs import create_publish_job

        job = create_publish_job(
            db,
            cluster_id=unit_id,
            scope_context=scope,
            user=user,
            public_base=_public_base(),
        )
    else:
        from ..seo_series.content.publish_jobs import create_publish_job

        job = create_publish_job(
            db,
            item_ids=[i.id for i in _approved(db, source, scope)],
            scope_context=scope,
            user=user,
            public_base=_public_base(),
        )
    db.commit()
    return {"job_id": job.job_id, "status": job.status}


__all__ = ["dispatch", "preview"]
