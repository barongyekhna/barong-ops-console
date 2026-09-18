"""A3 管控:五道护栏 + 每店总闸 + 超支熔断。任何级别都绕不过这里。

护栏(amz_guardrails,每店一行,没有就按默认建):
1. 每天总预算上限 daily_budget_cap(空 = 不设;影子期结束按真实水位定);
2. 单次出价调幅 ≤ bid_max_change_pct(默认 25%);
3. 单次预算调幅 ≤ budget_max_change_pct(默认 20%);
4. 每天自动动作条数 ≤ actions_per_day(默认 20);
5. 单次出价 ≤ cpc_max(空 = 不设)。
外加熔断:最近一天广告花费 ÷ 前 7 天日均 > breaker_ratio(默认 1.3)→ 自动拉下这家店的总闸(系统拉的,要人去开)。

总闸 kill_switch:拉下后这家店所有动作的有效级别都是 L0,倒计时中的 L2 立刻取消,worker 下一轮(≤15 秒)起不写任何东西。
拉闸谁都能拉(有「操作」角色就行);开闸只有老板。不 commit。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AmzActionLedger, AmzAdSearchTerm, AmzGuardrail

BREAKER_WINDOW_DAYS = 7
EXECUTED_STATUSES = ("executed",)


def guardrail(db: Session, store_code: str) -> AmzGuardrail:
    row = db.get(AmzGuardrail, store_code)
    if row is None:
        row = AmzGuardrail(store_code=store_code, bid_max_change_pct=25, budget_max_change_pct=20, actions_per_day=20, breaker_ratio=Decimal("1.3"), kill_switch=False)
        db.add(row)
        db.flush()
    return row


def guard_view(row: AmzGuardrail) -> dict[str, Any]:
    return {
        "daily_budget_cap": float(row.daily_budget_cap) if row.daily_budget_cap is not None else None,
        "bid_max_change_pct": row.bid_max_change_pct,
        "budget_max_change_pct": row.budget_max_change_pct,
        "actions_per_day": row.actions_per_day,
        "cpc_max": float(row.cpc_max) if row.cpc_max is not None else None,
        "breaker_ratio": float(row.breaker_ratio),
        "kill_switch": bool(row.kill_switch),
        "kill_switch_by_user_id": row.kill_switch_by_user_id,
        "kill_switch_at": row.kill_switch_at.isoformat() if row.kill_switch_at else None,
    }


EDITABLE = {"daily_budget_cap": (0, 100000), "bid_max_change_pct": (1, 50), "budget_max_change_pct": (1, 50), "actions_per_day": (0, 200), "cpc_max": (0.05, 20), "breaker_ratio": (1.05, 5)}


def update_guardrails(db: Session, store_code: str, values: dict[str, Any]) -> AmzGuardrail:
    """只收白名单字段,且每个都有上下限——护栏本身不能被调成没有护栏。"""
    row = guardrail(db, store_code)
    for key, raw in values.items():
        if key not in EDITABLE:
            continue
        low, high = EDITABLE[key]
        if raw is None and key in ("daily_budget_cap", "cpc_max"):
            setattr(row, key, None)
            continue
        value = float(raw)
        if not (low <= value <= high):
            raise ValueError(f"{key} 要在 {low} 到 {high} 之间")
        setattr(row, key, int(value) if key in ("bid_max_change_pct", "budget_max_change_pct", "actions_per_day") else Decimal(str(value)))
    db.add(row)
    db.flush()
    return row


def set_kill_switch(db: Session, store_code: str, *, on: bool, user_id: int | None, reason: str = "") -> AmzGuardrail:
    """拉闸:有效级别立刻归 L0,倒计时中的 L2 全部取消。"""
    row = guardrail(db, store_code)
    row.kill_switch = bool(on)
    row.kill_switch_by_user_id = user_id
    row.kill_switch_at = datetime.now(UTC)
    db.add(row)
    if on:
        for entry in db.scalars(select(AmzActionLedger).where(AmzActionLedger.store_code == store_code, AmzActionLedger.status.in_(("countdown", "queued", "waiting_api")))):
            entry.status = "cancelled"
            entry.blocked_reason = f"总闸拉下:{reason or '人工'}"
            db.add(entry)
    db.flush()
    return row


def spend_ratio(db: Session, store_code: str) -> tuple[float | None, date | None]:
    """最近一天花费 ÷ 前 7 天日均。数据不够返回 None。"""
    T = AmzAdSearchTerm
    last = db.scalar(select(func.max(T.report_date)).where(T.store_code == store_code))
    if last is None:
        return None, None
    rows = dict(db.execute(select(T.report_date, func.sum(T.spend)).where(T.store_code == store_code, T.report_date > last - timedelta(days=BREAKER_WINDOW_DAYS + 1)).group_by(T.report_date)).all())
    today = float(rows.get(last) or 0)
    prior = [float(v or 0) for d, v in rows.items() if d < last]
    if len(prior) < 3 or sum(prior) <= 0:
        return None, last
    return round(today / (sum(prior) / len(prior)), 2), last


def check_breaker(db: Session, store_code: str) -> dict[str, Any]:
    """超支熔断:比值过线就自动拉闸(系统拉的,要人开)。"""
    row = guardrail(db, store_code)
    ratio, day = spend_ratio(db, store_code)
    tripped = ratio is not None and ratio > float(row.breaker_ratio) and not row.kill_switch
    if tripped:
        set_kill_switch(db, store_code, on=True, user_id=None, reason=f"超支熔断:{day} 花费是前 7 天日均的 {ratio} 倍(线 {row.breaker_ratio})")
    return {"ratio": ratio, "day": day.isoformat() if day else None, "tripped": tripped}


def executed_today(db: Session, store_code: str, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    return int(db.scalar(select(func.count()).select_from(AmzActionLedger).where(AmzActionLedger.store_code == store_code, AmzActionLedger.status.in_(EXECUTED_STATUSES), AmzActionLedger.executed_at >= start)) or 0)


def check_op(db: Session, store_code: str, op: dict[str, Any], *, now: datetime | None = None) -> list[str]:
    """一条动作过五道护栏 + 总闸。返回违规原因(空 = 可以做)。"""
    row = guardrail(db, store_code)
    reasons: list[str] = []
    if row.kill_switch:
        reasons.append("总闸拉下")
    if executed_today(db, store_code, now=now) >= int(row.actions_per_day):
        reasons.append(f"今天已经做了 {row.actions_per_day} 条(每天上限)")
    change = op.get("change_pct")
    if change is not None:
        cap = row.budget_max_change_pct if op.get("kind") == "budget" else row.bid_max_change_pct
        if abs(float(change)) > float(cap):
            reasons.append(f"调幅 {change}% 超过上限 ±{cap}%")
    bid = op.get("bid")
    if bid is not None and row.cpc_max is not None and float(bid) > float(row.cpc_max):
        reasons.append(f"出价 {bid} 超过 CPC 上限 {row.cpc_max}")
    budget = op.get("daily_budget")
    if budget is not None and row.daily_budget_cap is not None and float(budget) > float(row.daily_budget_cap):
        reasons.append(f"日预算 {budget} 超过上限 {row.daily_budget_cap}")
    return reasons


__all__ = ["EDITABLE", "check_breaker", "check_op", "executed_today", "guard_view", "guardrail", "set_kill_switch", "spend_ratio", "update_guardrails"]
