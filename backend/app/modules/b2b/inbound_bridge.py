"""客服中心收到批发询盘 → 顺手落进 B2B 线索池。

2026-07-29:产品页小窗上的表单复用了 CS 的 `[barong_contact_form
channel="wholesale"]`——那条路已经在生产上跑着,有限流、有蜜罐、有通知。
**与其再开一个公开写入口(多一份攻击面),不如挂个下游钩子**,和 P 上架成功
后自动灌进批发目录是同一个套路。

主动找上门的线索和我们挖来的不一样:
- `status='new'` 但 `screen_verdict='fit'`——他自己举手了,比任何官网判断都准
- 用邮箱去重:同一家店多次询盘不该建出多行
- **绝不能把 CS 那边带崩**:整个函数包在 safely 里,出错只记日志
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .prospects.models import B2BProspect

logger = logging.getLogger(__name__)

# 小窗上的询盘都算批发线索。CS 的 retail 渠道不碰。
WHOLESALE_CHANNEL = "wholesale"
INBOUND_STORE_TYPE = "inbound"


def _text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def ingest_wholesale_inquiry(db: Session, message: Any) -> B2BProspect | None:
    """把一条 CS 批发询盘变成 B2B 线索。已存在则更新备注,不建重复行。"""
    channel = _text(getattr(message, "channel", ""), 32).lower()
    if channel != WHOLESALE_CHANNEL:
        return None

    email = _text(getattr(message, "email", ""), 255).lower()
    if not email:
        return None

    store_name = (
        _text(getattr(message, "company", ""), 255)
        or _text(getattr(message, "name", ""), 255)
        or email.split("@", 1)[0]
    )
    contact = _text(getattr(message, "name", ""), 128)
    body = _text(getattr(message, "message", ""), 4000)
    source = _text(getattr(message, "source_url", ""), 500)
    spam = _text(getattr(message, "status", ""), 16) == "spam"

    note = "\n".join(
        part
        for part in (
            "[产品页小窗询盘]",
            f"来源页: {source}" if source else "",
            f"联系人: {contact}" if contact else "",
            "",
            body,
        )
        if part != "" or True
    ).strip()[:4000]

    dedupe = f"inbound:{email}"
    existing = db.scalar(
        select(B2BProspect).where(B2BProspect.dedupe_key == dedupe)
    )
    if existing is not None:
        # 老客户又来问了:把新内容追加到备注,别建第二行。
        existing.notes = f"{note}\n\n---\n{existing.notes or ''}"[:4000]
        return existing

    prospect = B2BProspect(
        dedupe_key=dedupe,
        store_name=store_name,
        country="US",
        store_type=INBOUND_STORE_TYPE,
        language="en",
        email=email,
        email_verified=False,
        email_source="inbound_widget",
        contact_name=contact or None,
        # 主动找上门的不用机器筛——他自己举手了。
        screen_verdict="fit",
        screen_reason="主动从产品页小窗提交询盘（不是我们挖来的）",
        status="rejected" if spam else "new",
        reject_reason="CS 判为疑似垃圾提交" if spam else None,
        notes=note,
    )
    db.add(prospect)
    return prospect


def ingest_wholesale_inquiry_safely(db: Session, message: Any) -> None:
    """给 CS 入口用的包装:**B2B 出任何问题都不许把客服消息带崩。**"""
    try:
        ingest_wholesale_inquiry(db, message)
    except Exception:  # noqa: BLE001 - 客服消息优先
        logger.exception("B2B inbound bridge failed for CS message")
