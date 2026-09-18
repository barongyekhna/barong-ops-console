"""A3 执行:放行 / 倒计时到点 / L3 的建议 → 台账 → 过护栏 → 执行 → 回读 → 7/14/28 天回看。

执行这一步要 Ads API(还在审批)。现在的执行器是「未接入」:过完护栏的动作停在 waiting_api,
接上之后 ``get_executor`` 返回真的执行器,同一套流程原样跑——台账、护栏、回读、回看、降级都不用改。

状态:
- countdown   L2 已通报,倒计时中(期间驳回建议 = 取消)
- blocked     护栏拦下(原因写在 blocked_reason;算「碰护栏」,影响升级)
- waiting_api 护栏过了,等 Ads API 接入
- executed    做了;readback_ok 记回读对不对得上
- failed      执行报错
- cancelled   人驳回 / 总闸拉下
不 commit(调用方 commit)。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import control, experience, ladder, work_log
from .constants import EMPLOYEE_D
from .models import AmzActionLedger, AmzStore, AmzSuggestion

_LOGGER = logging.getLogger("amz.executor")

COUNTDOWN_HOURS = 24
LOOKBACK_DAYS = (7, 14, 28)
BID_DOWN_PCT = -20  # 精准倒挂 / 让位默认降两成(在 ±25% 护栏内)


class Executor(Protocol):
    def apply(self, store: AmzStore, op: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """执行一条动作,返回 (改前, 改后)。"""

    def readback(self, store: AmzStore, op: dict[str, Any], after: dict[str, Any]) -> bool:
        """执行后重新读一遍,核对亚马逊那边真的变成了 after。"""


def get_executor(db: Session, store: AmzStore) -> Executor | None:
    """Ads API 接入后在这里返回真的执行器。现在一律 None → 动作停在 waiting_api。"""
    return None


def plan_op(suggestion: AmzSuggestion) -> dict[str, Any] | None:
    """建议 → 具体要对广告后台做什么。证据不够具体就返回 None(不猜)。"""
    policy = ladder.ACTION_POLICY.get(suggestion.action_type)
    if policy is None:
        return None
    ev = suggestion.evidence_json or {}
    kind = policy.op
    if kind == "add_negative_exact":
        return {"op": kind, "term": ev.get("term"), "campaigns": ev.get("campaigns") or []} if ev.get("term") else None
    if kind == "add_exact_keyword":
        return {"op": kind, "term": ev.get("term"), "source_campaigns": ev.get("campaigns") or []} if ev.get("term") else None
    if kind == "lower_bid":
        if not (ev.get("campaign") and ev.get("target")):
            return None
        return {"op": kind, "kind": "bid", "campaign": ev["campaign"], "target": ev["target"], "change_pct": BID_DOWN_PCT}
    if kind == "yield_term":
        return {"op": kind, "kind": "bid", "term": ev.get("term"), "home_store": ev.get("home_store"), "change_pct": BID_DOWN_PCT} if ev.get("term") else None
    if kind in ("pause_sku_ads", "trim_sku_ads"):
        skus = ev.get("skus") or ([ev["sku"]] if ev.get("sku") else [])
        return {"op": kind, "kind": "bid", "asin": ev.get("asin"), "skus": skus, **({"change_pct": BID_DOWN_PCT} if kind == "trim_sku_ads" else {})} if skus else None
    if kind == "revert_budget":
        return {"op": kind, "kind": "budget", "to": "prior_week", "change_pct": -min(20, abs(float(ev.get("spend_delta_pct") or 20)))}
    return None


def _entry_for(db: Session, suggestion: AmzSuggestion, *, level: str, status: str, op: dict[str, Any], approved_by: int | None) -> AmzActionLedger:
    entry = db.scalar(select(AmzActionLedger).where(AmzActionLedger.suggestion_id == suggestion.id))
    if entry is None:
        entry = AmzActionLedger(suggestion_id=suggestion.id, store_code=suggestion.store_code, action_type=suggestion.action_type, level=level, status=status, op_json=op, why=suggestion.why, prediction=suggestion.prediction, approved_by_user_id=approved_by)
        db.add(entry)
        db.flush()
    return entry


def execute_entry(db: Session, entry: AmzActionLedger, *, store: AmzStore, executor: Executor | None, now: datetime | None = None) -> str:
    """过护栏 → 执行 → 回读。返回新状态。"""
    reasons = control.check_op(db, store.store_code, entry.op_json or {}, now=now)
    entry.guard_json = {"checked_at": (now or datetime.now(UTC)).isoformat(), "reasons": reasons}
    if reasons:
        entry.status, entry.blocked_reason = ("cancelled" if reasons == ["总闸拉下"] else "blocked"), ";".join(reasons)
    elif executor is None:
        entry.status, entry.blocked_reason = "waiting_api", "广告 API 还没接入:护栏已过,接上后自动执行"
    else:
        try:
            before, after = executor.apply(store, entry.op_json or {})
            entry.before_json, entry.after_json = before, after
            entry.executed_at = now or datetime.now(UTC)
            entry.readback_ok = bool(executor.readback(store, entry.op_json or {}, after))
            entry.status, entry.blocked_reason = "executed", None
            suggestion = db.get(AmzSuggestion, entry.suggestion_id)
            if suggestion is not None:
                suggestion.status = "executed"
                db.add(suggestion)
            work_log.record(db, employee=EMPLOYEE_D, kind="executed", title=f"已执行:{ladder.ACTION_POLICY[entry.action_type].label}({entry.level})", why=entry.why, store_code=store.store_code, subject=f"ledger|{entry.id}", detail={"op": entry.op_json, "before": before, "after": after, "readback_ok": entry.readback_ok}, source="api", suggestion_id=entry.suggestion_id)
        except Exception as exc:  # noqa: BLE001 — 一条失败不拖别的;原因进台账
            entry.status, entry.blocked_reason = "failed", str(exc)[:500]
    db.add(entry)
    db.flush()
    return entry.status


def process_store(db: Session, store: AmzStore, *, now: datetime | None = None, executor: Executor | None = None, use_default_executor: bool = True) -> dict[str, int]:
    """一轮:熔断检查 → 收新的(L1 放行 / L2 倒计时 / L3 直接)→ 到点的执行 → 等 API 的重试。"""
    now = now or datetime.now(UTC)
    counts = {"new": 0, "countdown": 0, "executed": 0, "blocked": 0, "waiting_api": 0, "cancelled": 0, "failed": 0, "skipped_no_detail": 0}
    breaker = control.check_breaker(db, store.store_code, today=now.date())
    if executor is None and use_default_executor:
        executor = get_executor(db, store)
    S = AmzSuggestion
    executable = tuple(ladder.ACTION_POLICY)
    # 被驳回的建议:倒计时 / 等待中的台账取消
    for entry in db.scalars(select(AmzActionLedger).join(S, S.id == AmzActionLedger.suggestion_id).where(AmzActionLedger.store_code == store.store_code, AmzActionLedger.status.in_(("countdown", "waiting_api")), S.status == "rejected")):
        entry.status, entry.blocked_reason = "cancelled", "人驳回了建议"
        db.add(entry)
        counts["cancelled"] += 1
    known = set(db.scalars(select(AmzActionLedger.suggestion_id).where(AmzActionLedger.store_code == store.store_code)))
    candidates = db.scalars(select(S).where(S.store_code == store.store_code, S.action_type.in_(executable), S.level.in_(("L1", "L2", "L3")), S.status.in_(("approved", "open"))))
    for suggestion in candidates:
        if suggestion.id in known:
            continue
        # L1 只收人放行的;L2/L3 开着的也收
        if suggestion.level == "L1" and suggestion.status != "approved":
            continue
        op = plan_op(suggestion)
        if op is None:
            counts["skipped_no_detail"] += 1
            continue
        if suggestion.level == "L2" and suggestion.status == "open":
            entry = _entry_for(db, suggestion, level="L2", status="countdown", op=op, approved_by=None)
            entry.countdown_until = now + timedelta(hours=COUNTDOWN_HOURS)
            db.add(entry)
            work_log.record(db, employee=EMPLOYEE_D, kind="note", title=f"倒计时 {COUNTDOWN_HOURS} 小时后执行:{suggestion.title}", why="L2:先通报后做。不同意就驳回这条建议,倒计时自动取消。", store_code=store.store_code, subject=f"ledger|countdown|{suggestion.id}", source="rule", suggestion_id=suggestion.id)
            counts["countdown"] += 1
            counts["new"] += 1
            continue
        entry = _entry_for(db, suggestion, level=suggestion.level, status="queued", op=op, approved_by=suggestion.decided_by_user_id)
        counts["new"] += 1
        counts[execute_entry(db, entry, store=store, executor=executor, now=now)] += 1
    # 倒计时到点的 + 等 API 的:再走一遍
    due = db.scalars(select(AmzActionLedger).where(AmzActionLedger.store_code == store.store_code, ((AmzActionLedger.status == "countdown") & (AmzActionLedger.countdown_until <= now)) | (AmzActionLedger.status == "waiting_api")))
    for entry in list(due):
        if ladder.effective_level(db, store.store_code, entry.action_type, today=now.date()) == "L0":
            entry.status, entry.blocked_reason = "cancelled", "有效级别回到 L0(影子期 / 总闸 / 降级)"
            db.add(entry)
            counts["cancelled"] += 1
            continue
        if entry.status == "waiting_api" and executor is None:
            continue
        counts[execute_entry(db, entry, store=store, executor=executor, now=now)] += 1
    db.flush()
    counts["breaker_tripped"] = int(bool(breaker.get("tripped")))
    return counts


def run_lookbacks(db: Session, store_code: str) -> int:
    """执行过的动作 7/14/28 天回看:同一个词 / 目标在执行后的窗口里表现如何(复用经验库的判法)。28 天那次定 outcome。"""
    _, last = experience.data_range(db, store_code)
    if last is None:
        return 0
    n = 0
    for entry in db.scalars(select(AmzActionLedger).where(AmzActionLedger.store_code == store_code, AmzActionLedger.status == "executed", AmzActionLedger.executed_at.is_not(None))):
        start = entry.executed_at.date()
        done = dict(entry.lookback_json or {})
        suggestion = db.get(AmzSuggestion, entry.suggestion_id)
        evidence = (suggestion.evidence_json if suggestion else {}) or {}
        changed = False
        for horizon in LOOKBACK_DAYS:
            key = f"d{horizon}"
            if key in done or start + timedelta(days=horizon) > last:
                continue
            window = experience._window_for(db, store_code=store_code, action_type=entry.action_type, evidence=evidence, subject="", start=start, end=start + timedelta(days=horizon))
            verdict = experience.judge(entry.action_type, window) if window is not None else "na"
            done[key] = {"verdict": verdict, "clicks": getattr(window, "clicks", None), "orders": getattr(window, "orders", None), "acos_pct": getattr(window, "acos", None)}
            changed = True
            n += 1
            if horizon == 28 and verdict in ("right", "wrong"):
                entry.outcome = verdict
        if changed:
            entry.lookback_json = done
            db.add(entry)
    db.flush()
    return n


def ledger_view(entry: AmzActionLedger) -> dict[str, Any]:
    policy = ladder.ACTION_POLICY.get(entry.action_type)
    return {
        "id": entry.id,
        "suggestion_id": str(entry.suggestion_id),
        "store_code": entry.store_code,
        "action_type": entry.action_type,
        "label": policy.label if policy else entry.action_type,
        "level": entry.level,
        "status": entry.status,
        "op": entry.op_json,
        "before": entry.before_json,
        "after": entry.after_json,
        "why": entry.why,
        "prediction": entry.prediction,
        "blocked_reason": entry.blocked_reason,
        "countdown_until": entry.countdown_until.isoformat() if entry.countdown_until else None,
        "executed_at": entry.executed_at.isoformat() if entry.executed_at else None,
        "readback_ok": entry.readback_ok,
        "lookback": entry.lookback_json,
        "outcome": entry.outcome,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def recent_ledger(db: Session, store_code: str, limit: int = 30) -> list[dict[str, Any]]:
    return [ledger_view(e) for e in db.scalars(select(AmzActionLedger).where(AmzActionLedger.store_code == store_code).order_by(AmzActionLedger.created_at.desc()).limit(limit))]


__all__ = ["COUNTDOWN_HOURS", "Executor", "execute_entry", "get_executor", "ledger_view", "plan_op", "process_store", "recent_ledger", "run_lookbacks"]
