"""内容台的写操作:批准 / 驳回 / 重写 / 解读。

三条纪律,每条都对应一个已经发生过或差点发生的问题:

**① 重写两边都走同步 orchestrator,绝不用 SEO 那个队列。**
``seo_generation_jobs.topic_id`` 上有真实外键 ``REFERENCES seo_topics(id)``,
而 SEO 的 revise 往这一列塞的是 ``SeoContentItem.id`` —— 一按就
ForeignKeyViolation。生产库里 4 条任务全是 generate、revise 零条,所以这个雷
从来没炸过(2026-08-02 排查内容台时才发现)。同步调 orchestrator 既绕开它,
又让两边行为一致:浮窗里只有一个「重写中…」,不需要两套加载逻辑。

**② 解读出网前必须先 ``db.commit()``。**
GEO 现有的 ``/geo/items/{id}/analyze`` 是带着读事务做 30 秒 DeepSeek 往返的
(``geo_series/router.py:530-538``)——**别照抄**。8 秒的 idle-in-transaction
收割器会把连接掐掉。照 ``geo_critique_summary`` 的写法。

**③ 调完 orchestrator 还要再 commit 一次并重新查询。**
两个 orchestrator 内部出网前是自己 commit 了,但 ``attach_analysis_to`` 有一条
「快照全空就早退、不 commit」的分支(``analysis_persist.py:43-44``),那种情况下
重写结果只 flush 过。而且 commit 会 expire 掉 ORM 对象,解读又是用独立 session
写回的,所以要返回给前端必须重新查。

**权限:进门看自己的键,动手看来源的键。** 见 ``sources.py`` 的说明。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..k_series.product_knowledge.scope_shim import KScopeContext
from .sources import ContentSource

logger = logging.getLogger(__name__)

REVIEW_STATUSES = ("pending", "approved", "rejected")


class DeskActionError(RuntimeError):
    """带 HTTP 状态码的业务错误,handler 直接转 HTTPException。"""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------- 批准 / 驳回


def set_review(
    db: Session,
    *,
    item: Any,
    source: ContentSource,
    review_status: str,
    user: Any | None,
) -> None:
    """写审阅状态。**不 commit**,由 handler 统一收尾。

    批准时的品牌门按来源表的 ``review_requires_clean`` 决定:SEO 在这里就拦,
    GEO 到发布才拦。这个不对称是历史事实,内容台如实反映而不是偷偷抹平——
    抹平的任一方向都会造成惊吓(要么突然批不动了,要么突然能批了)。
    """
    if review_status not in REVIEW_STATUSES:
        raise DeskActionError("未知审核状态。", status_code=400)

    if review_status == "approved" and source.review_requires_clean:
        from ..content_core.guards import audit_is_clean

        if not audit_is_clean(getattr(item, "brand_audit_json", None)):
            raise DeskActionError(
                "这篇没过品牌/接地审查，不能批准。"
                "把误报逐条放行，或者按批评重写。",
                status_code=409,
            )

    item.review_status = review_status
    # 这两列只有 GEO 有(SEO 表压根没建)。有就写,没有就算——
    # 不为了对称去加一条迁移。
    if hasattr(item, "reviewed_by_user_id"):
        from datetime import UTC, datetime

        item.reviewed_by_user_id = getattr(user, "id", None)
        item.reviewed_at = datetime.now(UTC)
    db.flush()


# ---------------------------------------------------------------- 重写


def revise(
    db: Session,
    *,
    item: Any,
    source: ContentSource,
    scope: KScopeContext,
    user: Any | None,
) -> None:
    """按批评重写。**同步**,两边都是(见模块 docstring ①)。

    调用方负责 commit + 重新查询。
    """
    item_id = item.id
    try:
        source.revise_fn(db, item_id, scope, user)
    except Exception as exc:  # noqa: BLE001 - 两边的错误类不同,统一成一种
        status_code = int(getattr(exc, "status_code", 0) or 0)
        message = str(getattr(exc, "message", "") or exc)
        if status_code:
            raise DeskActionError(message, status_code=status_code) from exc
        raise


# ---------------------------------------------------------------- 解读


def analyze(
    db: Session,
    *,
    item: Any,
    source: ContentSource,
    parent: Any,
    user: Any | None,
) -> bool:
    """(重新)跑一次 DeepSeek 解读。返回是否拿到结果。

    这条路同时补上 **SEO 侧根本没有的手动解读入口** —— 没有它,一篇解读失败的
    SEO 文章就死锁了:重写要求 risks 非空,而 risks 只能由解读产生。
    """
    from ..content_core.analysis import analyze_item

    item_id = item.id
    model = source.item_model_fn()
    topic = str(
        getattr(parent, source.parent_label_column, "") or getattr(item, "title", "")
    )

    # 🔴 出网前放掉事务。GEO 现有的 analyze 端点没做这件事,别照抄。
    db.commit()

    result = analyze_item(item, topic=topic, user=user)
    if result is None:
        return False

    # 用短事务写回:上面那次 commit 已经 expire 了 item。
    db.execute(update(model).where(model.id == item_id).values(analysis_json=result))
    db.commit()
    return True


__all__ = [
    "REVIEW_STATUSES",
    "DeskActionError",
    "analyze",
    "revise",
    "set_review",
]
