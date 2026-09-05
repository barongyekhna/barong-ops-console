"""审批 + 通知合成一张卡。

审批列表是全站唯一带语句超时的查询（`api/routes/approval.py` 1.8s）。这里沿用
同一超时；超时后必须 rollback，否则同一 session 后面的查询全部
`InFailedSqlTransaction`。超时只把审批分量标成 None，通知照常。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ...models.user import User
from ...services.approval_service import ApprovalService
from ..notifications import service as notifications_service
from .schemas import HomeCardItem, HomeCardRead

logger = logging.getLogger(__name__)

CARD_ID = "approvals"
APPROVAL_PAGE_LIMIT = 50
# 与 api/routes/approval.py::APPROVAL_LIST_DB_STATEMENT_TIMEOUT_MS 同值。
# 不从路由层 import：模块层反向依赖路由层会把 import 图绕成环。
APPROVAL_LIST_DB_STATEMENT_TIMEOUT_MS = 1800


def _apply_statement_timeout(db: Session) -> None:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    db.execute(text(f"SET LOCAL statement_timeout = {APPROVAL_LIST_DB_STATEMENT_TIMEOUT_MS}"))


def load_home_card(
    db: Session,
    *,
    workspace_key: str,
    user: User,
    permission_keys: frozenset[str],
    is_full_access: bool,
    governance_read: bool = False,
) -> HomeCardRead:
    user_id = str(user.id)
    unread = notifications_service.unread_count(db, user_id=user_id, org_id=workspace_key)
    notification_rows, _, _ = notifications_service.list_notifications(
        db, status="unread", limit=5, offset=0, user_id=user_id, org_id=workspace_key
    )

    approvals_count: int | None = None
    approval_items: list[HomeCardItem] = []
    degraded = False
    if governance_read:
        try:
            _apply_statement_timeout(db)
            page = ApprovalService(db).list_approval_page(
                user=user,
                status="pending",
                category=None,
                limit=APPROVAL_PAGE_LIMIT,
                offset=0,
            )
            approvals_count = len(page.items)
            for approval in page.items[:5]:
                approval_items.append(
                    HomeCardItem(
                        id=approval.approval_id,
                        title=f"审批 · {approval.module_key}/{approval.action_key}",
                        subtitle=(approval.reason or "")[:80],
                        at=approval.request_time,
                        href=f"/approvals?approval={approval.approval_id}",
                    )
                )
        except Exception:  # noqa: BLE001 - 超时/无权都只降级审批分量
            db.rollback()
            degraded = True
            logger.warning("home approvals card degraded", exc_info=True)

    items = list(approval_items)
    for row in notification_rows:
        if len(items) >= 5:
            break
        items.append(
            HomeCardItem(
                id=str(row.id),
                title=f"通知 · {row.title}",
                subtitle=(row.body or "")[:80],
                at=row.created_at,
                href=f"/notifications?notification={row.id}",
            )
        )

    actions: list[str] = []
    if governance_read and not degraded:
        actions.extend(["approve", "reject"])
    actions.append("read")

    extra: dict[str, Any] = {
        "approvals": approvals_count,
        "unread": unread,
        "approvals_capped": approvals_count == APPROVAL_PAGE_LIMIT,
        "approvals_degraded": degraded,
        "governance_read": governance_read,
    }
    return HomeCardRead(
        card_id=CARD_ID,
        module_key=None,
        count=(approvals_count or 0) + unread,
        items=items,
        freshness=datetime.now(UTC),
        actions=actions,
        extra=extra,
        severity="warn" if degraded else "ok",
    )
