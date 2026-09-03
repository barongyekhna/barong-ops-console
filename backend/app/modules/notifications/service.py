"""Data-access helpers for notifications. Kept import-light so other modules
(K / I / future P) can call ``create_notification`` directly in-process."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.orm import Session

from ...services.data_isolation import (
    SKIP_ORG_DATA_ISOLATION,
    without_org_data_isolation,
)
from .models import PNotification

logger = logging.getLogger(__name__)


def _org_id_for_product(db: Session, product_id: UUID) -> str | None:
    """顺着产品查它属于哪个组织。查不到就返回 None（不猜、不兜底到某个组织）。"""
    try:
        return db.scalar(
            text(
                "SELECT workspace_key FROM k_product_knowledge_products "
                "WHERE id = :pid"
            ),
            {"pid": str(product_id)},
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )
    except Exception:  # noqa: BLE001 - 推导不出来不该让通知本身发不出去
        logger.exception("notification org derivation failed: product=%s", product_id)
        return None

def create_notification(
    db: Session,
    *,
    event_type: str,
    title: str,
    body: str | None = None,
    level: str = "info",
    source: str = "system",
    org_id: str | None = None,
    recipient_user_id: str | None = None,
    product_id: UUID | None = None,
    external_refs: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> PNotification:
    # 组织归属：调用方没给就从产品推导。
    # 这些通知的生产者大多是 n8n 回调 / worker 内部函数，手边没有请求 scope；
    # 而 k_product_knowledge_products 带 workspace_key（就是 org_id 字符串），
    # 顺着 product_id 查一次就有了准确答案，比在 9 个调用点各猜一个表达式可靠。
    if org_id is None and product_id is not None:
        org_id = _org_id_for_product(db, product_id)

    row = PNotification(
        event_type=event_type,
        title=title,
        body=body,
        level=level,
        source=source,
        org_id=org_id,
        recipient_user_id=recipient_user_id,
        product_id=product_id,
        external_refs=external_refs,
        payload=payload,
        status="unread",
    )
    db.add(row)
    db.flush()
    return row


def _visible_to_user(user_id: str, *, org_id: str | None = None):
    recipient_filter = or_(
        PNotification.recipient_user_id.is_(None),
        PNotification.recipient_user_id == user_id,
    )
    if not org_id:
        # Preserve the service's historical behavior for internal callers that
        # do not carry an organization context. HTTP routes always pass one.
        return recipient_filter
    # 空 org **确实**表示「全站通知」（例如系统维护公告），这个语义是对的。
    #
    # 2026-08-31 体检发现的真问题不在这条判定,而在**生产者**:9 个业务通知生产者
    # 一个都没传 org_id,于是 205 条本该按组织隔离的业务通知(K 品牌门失败、
    # P 上传结果、站点死链,全都带具体 SKU)落成了「全站通知」,制造公司的超管
    # 一直在收国际贸易独立站的告警。
    #
    # 修法是在源头:create_notification 现在会从 product_id 推导 org_id
    # (见同文件 _org_id_for_product),新通知一律带组织归属;存量 205 条由
    # scripts/backfill_notification_org.py 回填。
    #
    # 一度把这条判定改成「空 org 只发给指名收件人」,那是修错了地方 ——
    # 它会让真正的全站公告发不出去(test_owner_targeted_notification_is_hidden_
    # from_other_users 当场抓到)。**症状出现在读取侧,病根在写入侧。**
    organization_filter = or_(
        PNotification.org_id.is_(None),
        PNotification.org_id == org_id,
    )
    return and_(recipient_filter, organization_filter)


def unread_count(
    db: Session,
    *,
    user_id: str,
    org_id: str | None = None,
) -> int:
    with without_org_data_isolation():
        return int(
            db.scalar(
                select(func.count())
                .select_from(PNotification)
                .where(
                    PNotification.status == "unread",
                    _visible_to_user(user_id, org_id=org_id),
                )
            )
            or 0
        )


def list_notifications(
    db: Session,
    *,
    status: str | None = None,
    level: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user_id: str,
    org_id: str | None = None,
) -> tuple[list[PNotification], int, int]:
    stmt = select(PNotification).where(
        _visible_to_user(user_id, org_id=org_id)
    )
    if status:
        stmt = stmt.where(PNotification.status == status)
    if level:
        stmt = stmt.where(PNotification.level == level)
    with without_org_data_isolation():
        total = int(
            db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        )
        ordered = stmt.order_by(
            PNotification.created_at.desc(), PNotification.id.desc()
        )
        rows = list(db.scalars(ordered.limit(limit).offset(offset)))
    return rows, total, unread_count(db, user_id=user_id, org_id=org_id)


def mark_read(
    db: Session,
    notification_id: int,
    *,
    user_id: str,
    org_id: str | None = None,
) -> int:
    with without_org_data_isolation():
        result = db.execute(
            update(PNotification)
            .where(
                PNotification.id == notification_id,
                PNotification.status == "unread",
                _visible_to_user(user_id, org_id=org_id),
            )
            .values(status="read", read_at=datetime.now(UTC))
        )
    return int(result.rowcount or 0)


def mark_all_read(
    db: Session,
    *,
    user_id: str,
    org_id: str | None = None,
) -> int:
    with without_org_data_isolation():
        result = db.execute(
            update(PNotification)
            .where(
                PNotification.status == "unread",
                _visible_to_user(user_id, org_id=org_id),
            )
            .values(status="read", read_at=datetime.now(UTC))
        )
    return int(result.rowcount or 0)
