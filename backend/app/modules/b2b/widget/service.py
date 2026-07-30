"""产品页小窗:决定推什么、什么时候推。

**推送内容在派单那一刻冻进 job 行**,包端点只是把它原样吐回去——绝不在包
端点里重新推导,否则派单后数据一变,n8n 拿到的和台账记的就是两回事。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..contract.widget_package import (
    WIDGET_META_KEY,
    WidgetPackage,
    WidgetTarget,
)
from ..wholesale.models import STATUS_READY, B2BWholesaleItem
from .jobs import create_widget_job
from .models import B2BWidgetJob

logger = logging.getLogger(__name__)


class WidgetError(RuntimeError):
    """人能看懂的错误,直接冒到界面上。"""


def build_target(item: B2BWholesaleItem) -> dict[str, Any] | None:
    """把一条批发记录变成一个推送目标。

    没上过 Woo 的产品(没有 woo_product_id)推不了——小窗挂在产品页上,
    产品页都不存在就无从谈起。
    """
    if not item.woo_product_id:
        return None
    available = item.status == STATUS_READY
    target = WidgetTarget(
        sku=item.sku,
        woo_product_id=int(item.woo_product_id),
        available=available,
        # 撤下时不带任何数据:插件读到 available=false 就什么都不渲染。
        moq_units=item.moq_units if available else None,
        case_pack=item.case_pack if available else None,
        lead_time_days=item.lead_time_days if available else None,
        variant_note=(item.variant_note or None) if available else None,
    )
    return target.model_dump(mode="json")


def collect_targets(
    db: Session,
    *,
    item_ids: list | None = None,
) -> list[dict[str, Any]]:
    """要推哪些产品。不传 item_ids 就是全量重推(政策改了用)。"""
    stmt = select(B2BWholesaleItem)
    if item_ids:
        stmt = stmt.where(B2BWholesaleItem.id.in_(item_ids))
    targets: list[dict[str, Any]] = []
    for item in db.scalars(stmt.order_by(B2BWholesaleItem.sku)):
        target = build_target(item)
        if target is not None:
            targets.append(target)
    return targets


def dispatch(
    db: Session,
    *,
    item_ids: list | None = None,
    user: Any | None = None,
    public_base: str,
) -> B2BWidgetJob:
    targets = collect_targets(db, item_ids=item_ids)
    if not targets:
        raise WidgetError(
            "没有可推送的产品：小窗挂在 Woo 产品页上，产品得先经 P 系列上架。"
        )
    return create_widget_job(
        db, targets=targets, user=user, public_base=public_base
    )


def dispatch_safely(
    db: Session,
    *,
    item_ids: list,
    public_base: str,
) -> None:
    """给批发信息保存路径用的包装:小窗推送出问题绝不能把保存带崩。"""
    try:
        dispatch(db, item_ids=item_ids, public_base=public_base)
    except Exception:  # noqa: BLE001 - 保存优先,推送失败只记日志
        logger.exception("B2B widget dispatch failed for items %s", item_ids)


def package_for(job: B2BWidgetJob) -> WidgetPackage:
    """把冻在 job 行里的目标原样吐回去。**绝不重新推导。**"""
    return WidgetPackage(
        job_id=job.job_id,
        channel=job.channel,
        generated_at=datetime.now(UTC),
        meta_key=WIDGET_META_KEY,
        targets=[WidgetTarget(**row) for row in (job.targets_json or [])],
    )
