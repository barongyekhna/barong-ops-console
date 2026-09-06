"""霓旌给制造公司主页的那张卡：她还活着吗、今天办了什么、被拦了什么。

她的待确认卡片在文件态（worker 的内存库），主页拿不到；能拿到的两样：
- `worker_heartbeats.nijing-worker`：最近一次真的干成活；
- `operation_logs`（actor_type="agent", actor_id="mfg.nijing"）：每一次入库/生产/发货/调整/撤销/被拦。
只 select。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....models.operation_log import OperationLog
from ....services.worker_heartbeat import list_heartbeats
from ...home.schemas import HomeCardItem, HomeCardRead
from ...m_series.home_card import factory_today_start
from .constants import AGENT_DISPLAY_NAME, AGENT_ID

CARD_ID = "nijing"
WORKER_NAME = "nijing-worker"
C19_HREF = "/c19"
ACTION_LABEL = {
    "agent.mfg.receipt": "入库",
    "agent.mfg.production": "生产",
    "agent.mfg.shipment": "发货",
    "agent.mfg.adjustment": "盘点调整",
    "agent.mfg.undo": "撤销",
    "agent.mfg.denied": "被门禁拦下",
    "agent.mfg.cancel": "取消",
    "agent.mfg.brain": "理解指令",
    "agent.chat.reply": "回复",
    "agent.bootstrap": "上岗",
}
RESULT_LABEL = {"success": "成功", "failure": "失败", "rejected": "拒绝", "denied": "无权"}
ATTENTION_RESULTS = ("denied", "rejected", "failure")


def _heartbeat(db: Session) -> dict[str, Any]:
    for beat in list_heartbeats(db):
        if beat["worker_name"] == WORKER_NAME:
            return {
                "last_success_at": beat["last_success_at"],
                "last_attempt_at": beat["last_attempt_at"],
                "stale": bool(beat["stale"]),
                "silent_seconds": beat["silent_seconds"],
                "consecutive_failures": beat["consecutive_failures"],
                "last_error": beat["last_error"],
                "expected_interval_seconds": beat["expected_interval_seconds"],
            }
    return {
        "last_success_at": None,
        "last_attempt_at": None,
        "stale": True,
        "silent_seconds": None,
        "consecutive_failures": 0,
        "last_error": None,
        "expected_interval_seconds": None,
    }


def load_home_card(
    db: Session,
    *,
    workspace_key: str,
    user: Any,
    permission_keys: frozenset[str],
    is_full_access: bool,
    now: datetime | None = None,
    **_: Any,
) -> HomeCardRead:
    heartbeat = _heartbeat(db)
    base = (
        OperationLog.actor_type == "agent",
        OperationLog.actor_id == AGENT_ID,
        OperationLog.org_id == workspace_key,
    )
    recent = db.scalars(
        select(OperationLog).where(*base).order_by(OperationLog.id.desc()).limit(10)
    ).all()
    day_start = factory_today_start(now)
    today_rows = db.scalars(
        select(OperationLog).where(*base, OperationLog.created_at >= day_start)
    ).all()
    today = {key: 0 for key in ("success", "failure", "rejected", "denied")}
    for row in today_rows:
        if row.action in ("agent.mfg.brain", "agent.chat.reply"):
            continue  # 思考和回话不算「办事」
        today[row.result] = today.get(row.result, 0) + 1

    def label(row: OperationLog) -> str:
        return f"{ACTION_LABEL.get(row.action, row.action)} · {RESULT_LABEL.get(row.result, row.result)}"

    items = [
        HomeCardItem(
            id=str(row.id),
            title=label(row),
            subtitle=" · ".join(part for part in (row.target_type, row.target_id, row.error_code or "") if part)[:120],
            at=row.created_at,
            href=C19_HREF,
        )
        for row in recent
        if row.action not in ("agent.mfg.brain", "agent.chat.reply")
    ][:5]

    attention = sum(today.get(key, 0) for key in ATTENTION_RESULTS)
    severity = "error" if heartbeat["stale"] else ("warn" if attention else "ok")
    return HomeCardRead(
        card_id=CARD_ID,
        module_key=None,
        count=attention,
        items=items,
        freshness=datetime.now(UTC),
        actions=[],
        extra={
            "agent_name": AGENT_DISPLAY_NAME,
            "heartbeat": heartbeat,
            "today": today,
            "recent": [
                {
                    "id": str(row.id),
                    "action": row.action,
                    "action_label": ACTION_LABEL.get(row.action, row.action),
                    "result": row.result,
                    "result_label": RESULT_LABEL.get(row.result, row.result),
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                    "error_code": row.error_code,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in recent
            ],
        },
        severity=severity,
    )
