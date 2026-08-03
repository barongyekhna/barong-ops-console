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
    """每个发布单元:会发哪几篇、被什么挡着。

    **开头会回读一次产品在 Woo 上的当前地址**(10 分钟内不重复)。原因:P 首次
    上架故意落草稿,存的是草稿期的丑地址;用户后来在 WP 后台点了发布,没有任何
    东西回来更新过。2026-08-02 用户五个捏捏全发布了,这里却还在说「产品还没有
    公开的产品页」——**陈旧数据造成的误报,比没有检查更糟**:它让人怀疑一个
    其实是对的门禁。
    """
    from ..content_links.product_state import refresh_product_permalinks_safely

    refresh_product_permalinks_safely(db)

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


def in_flight(db: Session) -> list[dict[str, Any]]:
    """还在飞的派单。

    派单到 n8n 回报之间有 ~30 秒窗口。这段时间文章还没有 wp_post_id,所以它
    仍然出现在待发列表里 —— 用户会以为「点了没反应」。把在飞的报出来,前端据此
    把按钮换成「派单中…」并置灰。
    """
    out: list[dict[str, Any]] = []
    try:
        from ..geo_series.content.models import GeoPublishJob

        for job in db.execute(
            select(GeoPublishJob).where(GeoPublishJob.status.in_(("queued", "dispatched")))
        ).scalars():
            out.append(
                {
                    "source": SOURCES[0].key,
                    "unit_id": str(job.cluster_id),
                    "job_id": job.job_id,
                    "status": job.status,
                }
            )
    except Exception:  # noqa: BLE001
        logger.exception("geo in-flight probe failed")
    try:
        from ..seo_series.content.models import SeoPublishJob

        for job in db.execute(
            select(SeoPublishJob).where(SeoPublishJob.status.in_(("queued", "dispatched")))
        ).scalars():
            out.append(
                {
                    "source": SOURCES[1].key,
                    "unit_id": SOURCES[1].key,
                    "job_id": job.job_id,
                    "status": job.status,
                }
            )
    except Exception:  # noqa: BLE001
        logger.exception("seo in-flight probe failed")
    return out


def landed(db: Session, *, scope: KScopeContext | None = None) -> dict[str, list[dict[str, Any]]]:
    """已经发到站上的文章,按「还是草稿」和「真的在线上」分开。

    **这一段原本完全不存在,是最要命的缺口。** n8n **刻意**把文章落成草稿等人工
    发布(P 系列同规),所以派单成功 ≠ 读者能看到。2026-08-03 用户发了两篇指南,
    任务 success、地址也有,但匿名访问是 404 —— 而内容台从没告诉过他还有
    「去 WordPress 点发布」这一步。

    发布成功的战报只说到派单,不说到读者能不能看见,那就是**报了个假成功**。
    """
    drafts: list[dict[str, Any]] = []
    live: list[dict[str, Any]] = []
    for source in SOURCES:
        model = source.item_model_fn()
        query = apply_scope_filters(select(model), model, scope).where(
            model.wp_post_id.is_not(None)
        )
        for item in db.execute(query).scalars():
            row = {
                "source": source.key,
                "id": str(item.id),
                "title": str(item.title or ""),
                "wp_post_id": item.wp_post_id,
                "wp_status": item.wp_status,
                "url": item.published_url,
            }
            (live if item.wp_status == "publish" else drafts).append(row)
    drafts.sort(key=lambda r: r["title"])
    live.sort(key=lambda r: r["title"])
    return {"drafts": drafts, "live": live}


def refresh_live_state_safely(db: Session) -> None:
    """回读文章在 WP 上的真实状态。

    用户在 WordPress 后台点发布,控制台**永远不会自动知道** —— 除非回来看一眼。
    (和产品地址那条是同一类问题,同一天连着栽了两次。)
    """
    for label, fn in (
        ("geo", "geo_series.content.live_state"),
        ("seo", "seo_series.content.live_state"),
    ):
        try:
            module = __import__(
                f"backend.app.modules.{fn}", fromlist=["refresh_item_live_state_safely"]
            )
            module.refresh_item_live_state_safely(db)
        except Exception:  # noqa: BLE001 - 回读失败不该让整页打不开
            logger.exception("%s live-state refresh failed", label)


__all__ = ["dispatch", "in_flight", "landed", "preview", "refresh_live_state_safely"]
