"""办公室要显示的东西:五种状态怎么判、今日数字、流水、目标、卡片。

状态规则(按顺序,先命中为准;动画只由这里的真实数据驱动):
1. 掉线 offline —— 业务心跳超过 3 个间隔没成功(worker_heartbeats 的 stale)。
2. 夜班 night  —— 洛杉矶 22:00–08:00,而且她还活着。
3. 在想 thinking —— sqh_state.activity=thinking 且 2 分钟内写的。
4. 举手 raised —— 有待审卡。
5. 干活 working —— 以上都不是。
暂停是另外叠的一个标记,不占五种状态。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from ....services.worker_heartbeat import list_heartbeats
from . import cards
from .constants import LA, NIGHT_END_HOUR, NIGHT_START_HOUR, THINKING_FRESH_SECONDS, USAGE_LABEL, WORKER_NAME
from .models import SqhActivity, SqhCard, SqhGoal, SqhSnapshot, SqhState

_X = SKIP_ORG_DATA_ISOLATION


def get_state(db: Session) -> SqhState:
    row = db.get(SqhState, 1)
    if row is None:
        row = SqhState(id=1)
        db.add(row)
        db.flush()
    return row


def heartbeat(db: Session) -> dict[str, Any] | None:
    for row in list_heartbeats(db):
        if row["worker_name"] == WORKER_NAME:
            return row
    return None


def is_night(now: datetime | None = None) -> bool:
    hour = (now or datetime.now(UTC)).astimezone(LA).hour
    return hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR


def compute_state(
    *,
    beat: dict[str, Any] | None,
    activity: str,
    activity_updated_at: datetime | None,
    pending: int,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(UTC)
    if beat is None or beat.get("stale"):
        return "offline"
    if is_night(now):
        return "night"
    if (
        activity == "thinking"
        and activity_updated_at is not None
        and now - activity_updated_at <= timedelta(seconds=THINKING_FRESH_SECONDS)
    ):
        return "thinking"
    if pending > 0:
        return "raised"
    return "working"


def _today_la_bounds(now: datetime) -> tuple[datetime, datetime]:
    local = now.astimezone(LA)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _claude_spend_today(db: Session) -> float | None:
    from sqlalchemy import text

    try:
        value = db.execute(
            text(
                "SELECT COALESCE(SUM(cost_usd),0) FROM ai_usage_ledger "
                "WHERE usage_day = (now() AT TIME ZONE 'UTC')::date AND module = :m"
            ),
            {"m": USAGE_LABEL},
            execution_options=_X,
        ).scalar()
        return round(float(value or 0), 4)
    except Exception:  # noqa: BLE001 —— 办公室显示不能因为台账表读不到而整页挂掉
        db.rollback()
        return None


def office_payload(db: Session, *, can_command: bool, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    state = get_state(db)
    beat = heartbeat(db)
    pending = list(cards.pending_cards(db))
    start, end = _today_la_bounds(now)
    decided_today = db.scalar(
        select(func.count()).select_from(SqhCard).where(SqhCard.decided_at >= start, SqhCard.decided_at < end),
        execution_options=_X,
    ) or 0
    created_today = db.scalar(
        select(func.count()).select_from(SqhCard).where(SqhCard.created_at >= start, SqhCard.created_at < end),
        execution_options=_X,
    ) or 0
    activity_rows = list(
        db.scalars(select(SqhActivity).order_by(SqhActivity.created_at.desc(), SqhActivity.id.desc()).limit(30), execution_options=_X)
    )
    recent_cards = list(
        db.scalars(
            select(SqhCard).where(SqhCard.status != "pending").order_by(SqhCard.decided_at.desc().nullslast()).limit(10),
            execution_options=_X,
        )
    )
    goals = list(
        db.scalars(select(SqhGoal).where(SqhGoal.status.in_(("active", "paused"))).order_by(SqhGoal.created_at), execution_options=_X)
    )
    snapshot = db.scalar(select(SqhSnapshot).order_by(SqhSnapshot.snapshot_date.desc()).limit(1), execution_options=_X)
    office_state = compute_state(
        beat=beat,
        activity=state.activity,
        activity_updated_at=state.updated_at,
        pending=len(pending),
        now=now,
    )
    headline = (snapshot.payload or {}).get("headline") if snapshot is not None and isinstance(snapshot.payload, dict) else None
    return {
        "state": office_state,
        "paused": bool(state.paused),
        "task": state.task,
        "progress": state.progress,
        "state_updated_at": state.updated_at.isoformat() if state.updated_at else None,
        "heartbeat": {
            "last_success_at": beat.get("last_success_at") if beat else None,
            "silent_seconds": beat.get("silent_seconds") if beat else None,
            "stale": bool(beat.get("stale")) if beat else True,
        },
        "today": {
            "cards_created": int(created_today),
            "cards_decided": int(decided_today),
            "cards_pending": len(pending),
            "claude_usd": _claude_spend_today(db),
        },
        "snapshot": {
            "date": snapshot.snapshot_date.isoformat() if snapshot is not None else None,
            "headline": headline,
        },
        "goals": [
            {"id": g.id, "text": g.text, "metric": g.metric, "status": g.status} for g in goals
        ],
        "pending_cards": [cards.card_payload(c) for c in pending],
        "recent_cards": [cards.card_payload(c) for c in recent_cards],
        "activity": [
            {"id": a.id, "kind": a.kind, "text": a.text, "at": a.created_at.isoformat() if a.created_at else None}
            for a in activity_rows
        ],
        "can_command": can_command,
        "server_time": now.isoformat(),
    }
