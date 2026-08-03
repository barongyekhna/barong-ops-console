"""回读产品在 Woo 上的**当前**地址。

由来(2026-08-02):用户把五个捏捏在 WooCommerce 里全发布了,内容台却仍然说
「内容里引用的产品还没有公开的产品页」。查下来是**陈旧数据造成的误报**:

- P 首次上架**故意落草稿**,所以 ``p_upload_jobs.external_url`` 存的是草稿期的
  丑地址 ``?post_type=product&p=4025``
- 用户后来在 WP 后台点了发布,地址变成 ``/product/squeeze-ball-adults-slow-rebound/``
- **但没有任何东西回来把它更新过** —— 发布门禁读的还是上传那一刻的值

这是「外部副作用要回读验证」那条死规矩的镜像面:那条管「我写出去的到底成没成」,
这条管「我写出去之后,外面又变成什么样了」。人在 WP 后台的操作,控制台永远不会
自动知道 —— 除非回来看一眼。

``external_url`` 的语义因此从「上传那一刻的地址」改成「**我们最后一次看到的
地址**」。这与 P 自己的行为一致:重新上架时它也会覆写这一列。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

REFRESH_KEY = "product_permalinks_checked_at"
# 别为每次开页面都打一遍 Woo。10 分钟足够覆盖「刚在后台点了发布,回来看结果」。
MIN_REFRESH_INTERVAL_MINUTES = 10


def _due(db: Session, *, force: bool) -> bool:
    if force:
        return True
    from .link_push import _get

    raw = str(_get(db, REFRESH_KEY) or "")
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return datetime.now(UTC) - last >= timedelta(minutes=MIN_REFRESH_INTERVAL_MINUTES)


def refresh_product_permalinks(db: Session, *, force: bool = False) -> dict[str, Any]:
    """把「存的还是草稿地址」的那些产品,按 Woo 现状更新一遍。

    **只往好的方向改**:拿到公开地址才写回。Woo 打不通、或某个产品查不到,
    一律保留现状 —— 宁可继续拦着,也不能凭一次网络抖动把一个真草稿放出去。
    """
    from ..geo_series.content.product_links import _is_public_permalink
    from ..p_series.upload.models import PUploadJob
    from .link_push import _set

    if not _due(db, force=force):
        return {"checked": False, "reason": "距上次回读不足间隔"}

    # 每个产品最近一次成功上架的那条。只挑存的还不是公开地址的。
    rows = db.execute(
        select(
            PUploadJob.id,
            PUploadJob.product_id,
            PUploadJob.external_product_id,
            PUploadJob.external_url,
            PUploadJob.finished_at,
        )
        .where(
            PUploadJob.status == "success",
            PUploadJob.external_product_id.is_not(None),
        )
        .order_by(PUploadJob.finished_at.desc(), PUploadJob.created_at.desc())
    ).all()

    latest: dict[Any, tuple[Any, int, str]] = {}
    for job_id, product_id, woo_id, url, _finished in rows:
        if product_id in latest:
            continue
        latest[product_id] = (job_id, int(woo_id), str(url or ""))

    stale = {
        product_id: value
        for product_id, value in latest.items()
        if not _is_public_permalink(value[2])
    }
    if not stale:
        _set(db, REFRESH_KEY, datetime.now(UTC).isoformat())
        db.commit()
        return {"checked": True, "stale": 0, "updated": 0}

    # 🔴 出网前放掉事务。
    db.commit()

    from ..content_core.wc_sync import fetch_product_states_safely

    states = fetch_product_states_safely(db, [v[1] for v in stale.values()])
    if states is None:
        # 核不了就保留现状,**绝不因为一次抖动改判**。
        return {"checked": True, "stale": len(stale), "updated": 0, "reason": "Woo 打不通"}

    updated = 0
    for _product_id, (job_id, woo_id, _old) in stale.items():
        state = states.get(woo_id)
        if not state:
            continue
        permalink = str(state.get("permalink") or "").strip()
        if state.get("status") != "publish" or not _is_public_permalink(permalink):
            continue  # 还真是草稿 / 还真没有正式地址 —— 该拦就拦
        job = db.get(PUploadJob, job_id)
        if job is not None:
            job.external_url = permalink
            updated += 1
    _set(db, REFRESH_KEY, datetime.now(UTC).isoformat())
    db.commit()
    return {"checked": True, "stale": len(stale), "updated": updated}


def refresh_product_permalinks_safely(db: Session, *, force: bool = False) -> dict[str, Any]:
    """回读失败绝不该让发布预览打不开。"""
    try:
        return refresh_product_permalinks(db, force=force)
    except Exception as exc:  # noqa: BLE001
        logger.exception("product permalink refresh failed")
        return {"checked": False, "reason": str(exc)[:120]}


__all__ = [
    "MIN_REFRESH_INTERVAL_MINUTES",
    "REFRESH_KEY",
    "refresh_product_permalinks",
    "refresh_product_permalinks_safely",
]
