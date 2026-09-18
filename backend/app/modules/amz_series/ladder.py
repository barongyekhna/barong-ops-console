"""A3 自动化梯子:按「动作 × 店铺」四级爬。升要人批,降自动。

L0 影子:只出建议,放行也只是记录;
L1 人批了才做:放行 → 过护栏 → 执行 → 回读 → 台账;
L2 先通报后做:出建议即进 24 小时倒计时,期间人可以驳回;没人拦就执行;
L3 直接做:过护栏就执行,事后通报。

家规:
- 影子期(2026-09-16 起至少 30 天)内所有店所有动作有效级别都是 L0;
- 改价 / 标题 / 主图 / 建删 campaign / 排产 / 图片线永远停在 L1 以下——系统只出建议,不执行(不在 ACTION_POLICY 里就是不可执行);
- 升级条件:当前级别满 30 天 + 近 60 天拍板 ≥ 10 条 + 采纳率 ≥ 70% + 28 天回看命中率 ≥ 60%(≥ 6 条)+ 近 30 天零护栏触碰;
  满足就出一条「升级提议」建议(action ladder_upgrade),老板或有授权角色的人放行才升;
- 自动降级:回读失败 → 直接降到 L1;近 21 天回看错的 ≥ 一半(≥ 4 条)→ 降一级;每次都写进 history 和工作日志。
不 commit。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import work_log
from .constants import EMPLOYEE_D
from .models import AmzActionLedger, AmzLadder, AmzOutcome, AmzSuggestion

LEVELS = ("L0", "L1", "L2", "L3")
SHADOW_START = date(2026, 9, 16)
SHADOW_MIN_DAYS = 30
SHADOW_UNTIL = SHADOW_START + timedelta(days=SHADOW_MIN_DAYS)

UPGRADE_MIN_DAYS = 30
UPGRADE_MIN_DECISIONS = 10
UPGRADE_MIN_APPROVAL_PCT = 70.0
UPGRADE_MIN_PRECISION_PCT = 60.0
UPGRADE_MIN_OUTCOMES = 6
DOWNGRADE_WINDOW_DAYS = 21
DOWNGRADE_MIN_JUDGED = 4
ACTION_LADDER_UPGRADE = "ladder_upgrade"


@dataclass(frozen=True)
class Policy:
    op: str
    label: str
    max_level: str


# 可以由系统执行的动作(接 Ads API 后)。不在这里的 = 只出建议,永远人做。
ACTION_POLICY: dict[str, Policy] = {
    "negative": Policy("add_negative_exact", "否词(否定精准)", "L3"),
    "harvest": Policy("add_exact_keyword", "收割赢家词进精准组", "L2"),
    "bid_down": Policy("lower_bid", "精准倒挂降出价", "L2"),
    "portfolio_yield": Policy("yield_term", "主场词让位(降出价)", "L2"),
    "stockout": Policy("pause_sku_ads", "断货停广告", "L2"),
    "stock_cover": Policy("trim_sku_ads", "库存紧张收广告", "L2"),
    "spend_without_sales": Policy("revert_budget", "花费涨销量没涨退预算", "L1"),
}


def rank(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else 0


def in_shadow(today: date | None = None) -> bool:
    return (today or datetime.now(UTC).date()) < SHADOW_UNTIL


def ladder_row(db: Session, store_code: str, action_type: str) -> AmzLadder | None:
    policy = ACTION_POLICY.get(action_type)
    if policy is None:
        return None
    row = db.get(AmzLadder, (store_code, action_type))
    if row is None:
        row = AmzLadder(store_code=store_code, action_type=action_type, level="L0", max_level=policy.max_level, history_json=[])
        db.add(row)
        db.flush()
    return row


def effective_level(db: Session, store_code: str, action_type: str, *, today: date | None = None) -> str:
    """真正生效的级别 = min(梯子上的级别, 这个动作的封顶),影子期 / 总闸拉下 → L0,不可执行的动作 → L0。"""
    from .control import guardrail  # noqa: PLC0415

    policy = ACTION_POLICY.get(action_type)
    if policy is None or in_shadow(today):
        return "L0"
    if guardrail(db, store_code).kill_switch:
        return "L0"
    row = ladder_row(db, store_code, action_type)
    level = row.level if row is not None else "L0"
    return LEVELS[min(rank(level), rank(policy.max_level))]


def _history(row: AmzLadder, *, to: str, why: str, by: int | None) -> None:
    row.history_json = [*(row.history_json or []), {"from": row.level, "to": to, "why": why, "by_user_id": by, "at": datetime.now(UTC).isoformat()}]
    row.level = to


def set_level(db: Session, store_code: str, action_type: str, *, to: str, why: str, by: int | None) -> AmzLadder:
    row = ladder_row(db, store_code, action_type)
    if row is None:
        raise ValueError(f"{action_type} 不可执行,没有梯子")
    policy = ACTION_POLICY[action_type]
    if rank(to) > rank(policy.max_level):
        raise ValueError(f"{policy.label} 最高只能到 {policy.max_level}")
    if to != row.level:
        _history(row, to=to, why=why, by=by)
        db.add(row)
        work_log.record(db, employee=EMPLOYEE_D, kind="note", title=f"{store_code} 的「{policy.label}」级别 → {to}", why=why, store_code=store_code, subject=f"ladder|{action_type}", detail={"to": to}, source="human" if by else "rule", actor_user_id=by)
    db.flush()
    return row


def _level_since(row: AmzLadder) -> date:
    hist = row.history_json or []
    if hist:
        try:
            return datetime.fromisoformat(hist[-1]["at"]).date()
        except (KeyError, ValueError):
            pass
    return SHADOW_START


def upgrade_stats(db: Session, store_code: str, action_type: str, *, today: date) -> dict[str, Any]:
    S = AmzSuggestion
    decided = dict(db.execute(select(S.status, func.count()).where(S.store_code == store_code, S.action_type == action_type, S.status.in_(("approved", "rejected", "executed")), S.decided_at >= datetime.combine(today - timedelta(days=60), datetime.min.time(), tzinfo=UTC)).group_by(S.status)).all())
    approved = int(decided.get("approved", 0)) + int(decided.get("executed", 0))
    total = approved + int(decided.get("rejected", 0))
    outcomes = dict(db.execute(select(AmzOutcome.verdict, func.count()).where(AmzOutcome.store_code == store_code, AmzOutcome.action_type == action_type, AmzOutcome.horizon_days == 28, AmzOutcome.verdict.in_(("right", "wrong"))).group_by(AmzOutcome.verdict)).all())
    right, wrong = int(outcomes.get("right", 0)), int(outcomes.get("wrong", 0))
    guard_hits = int(db.scalar(select(func.count()).select_from(AmzActionLedger).where(AmzActionLedger.store_code == store_code, AmzActionLedger.action_type == action_type, AmzActionLedger.status == "blocked", AmzActionLedger.created_at >= datetime.combine(today - timedelta(days=30), datetime.min.time(), tzinfo=UTC))) or 0)
    return {
        "decisions": total,
        "approval_pct": round(approved / total * 100, 1) if total else None,
        "outcomes": right + wrong,
        "precision_pct": round(right / (right + wrong) * 100, 1) if right + wrong else None,
        "guard_hits_30d": guard_hits,
    }


def upgrade_ready(stats: dict[str, Any], *, days_at_level: int) -> tuple[bool, list[str]]:
    missing = []
    if days_at_level < UPGRADE_MIN_DAYS:
        missing.append(f"当前级别才 {days_at_level} 天(要 {UPGRADE_MIN_DAYS})")
    if stats["decisions"] < UPGRADE_MIN_DECISIONS:
        missing.append(f"近 60 天拍板 {stats['decisions']} 条(要 {UPGRADE_MIN_DECISIONS})")
    if stats["approval_pct"] is None or stats["approval_pct"] < UPGRADE_MIN_APPROVAL_PCT:
        missing.append(f"采纳率 {stats['approval_pct']}%(要 {UPGRADE_MIN_APPROVAL_PCT:g}%)")
    if stats["outcomes"] < UPGRADE_MIN_OUTCOMES or (stats["precision_pct"] or 0) < UPGRADE_MIN_PRECISION_PCT:
        missing.append(f"28 天回看命中 {stats['precision_pct']}%/{stats['outcomes']} 条(要 {UPGRADE_MIN_PRECISION_PCT:g}%、≥{UPGRADE_MIN_OUTCOMES} 条)")
    if stats["guard_hits_30d"]:
        missing.append(f"近 30 天碰过护栏 {stats['guard_hits_30d']} 次")
    return not missing, missing


def propose_upgrades(db: Session, store_code: str, *, today: date | None = None) -> int:
    """够条件的(店 × 动作)出一条升级提议;影子期、总闸拉下时不提。"""
    from .control import guardrail  # noqa: PLC0415
    from .rules import SuggestionDraft  # noqa: PLC0415

    today = today or datetime.now(UTC).date()
    if in_shadow(today) or guardrail(db, store_code).kill_switch:
        return 0
    n = 0
    for action_type, policy in ACTION_POLICY.items():
        row = ladder_row(db, store_code, action_type)
        if row is None or rank(row.level) >= rank(policy.max_level):
            continue
        stats = upgrade_stats(db, store_code, action_type, today=today)
        ok, _missing = upgrade_ready(stats, days_at_level=(today - _level_since(row)).days)
        if not ok:
            continue
        to = LEVELS[rank(row.level) + 1]
        draft = SuggestionDraft(
            employee=EMPLOYEE_D,
            store_code=store_code,
            action_type=ACTION_LADDER_UPGRADE,
            severity="info",
            title=f"{store_code} 的「{policy.label}」可以从 {row.level} 升到 {to}",
            why=f"近 60 天拍板 {stats['decisions']} 条、采纳 {stats['approval_pct']}%;28 天回看命中 {stats['precision_pct']}%({stats['outcomes']} 条);近 30 天没碰过护栏。",
            prediction={"L1": "升到 L1:你放行后系统去做,做完回读核对。", "L2": "升到 L2:出建议后倒计时 24 小时,你不拦就做。", "L3": "升到 L3:过护栏就直接做,事后通报。"}[to],
            subject=f"ladder|{action_type}|{to}",
            evidence={"action_type": action_type, "from": row.level, "to": to, "stats": stats},
        )
        from .rules import upsert_drafts  # noqa: PLC0415

        n += upsert_drafts(db, [draft], as_of=today)["created"]
    return n


def apply_upgrade(db: Session, suggestion: AmzSuggestion, *, user_id: int) -> AmzLadder | None:
    ev = suggestion.evidence_json or {}
    action_type, to = ev.get("action_type"), ev.get("to")
    if action_type not in ACTION_POLICY or to not in LEVELS:
        return None
    row = ladder_row(db, suggestion.store_code, action_type)
    if row is None or rank(to) != rank(row.level) + 1:
        return None  # 提议过期了(期间已经降级 / 升过)
    return set_level(db, suggestion.store_code, action_type, to=to, why=f"人放行升级提议:{suggestion.why}", by=user_id)


def auto_downgrade(db: Session, store_code: str, *, today: date | None = None) -> list[dict[str, Any]]:
    today = today or datetime.now(UTC).date()
    since = datetime.combine(today - timedelta(days=DOWNGRADE_WINDOW_DAYS), datetime.min.time(), tzinfo=UTC)
    out = []
    for action_type in ACTION_POLICY:
        row = db.get(AmzLadder, (store_code, action_type))
        if row is None or row.level == "L0":
            continue
        entries = list(db.scalars(select(AmzActionLedger).where(AmzActionLedger.store_code == store_code, AmzActionLedger.action_type == action_type, AmzActionLedger.executed_at >= since)))
        readback_fail = [e for e in entries if e.readback_ok is False]
        judged = [e for e in entries if e.outcome in ("right", "wrong")]
        wrong = [e for e in judged if e.outcome == "wrong"]
        to, why = None, ""
        if readback_fail and rank(row.level) > rank("L1"):
            to, why = "L1", f"近 {DOWNGRADE_WINDOW_DAYS} 天有 {len(readback_fail)} 条执行后回读对不上"
        elif len(judged) >= DOWNGRADE_MIN_JUDGED and len(wrong) * 2 >= len(judged):
            to, why = LEVELS[rank(row.level) - 1], f"近 {DOWNGRADE_WINDOW_DAYS} 天回看 {len(judged)} 条错了 {len(wrong)} 条"
        if to:
            set_level(db, store_code, action_type, to=to, why=f"自动降级:{why}", by=None)
            out.append({"action_type": action_type, "to": to, "why": why})
    return out


def ladder_view(db: Session, store_code: str, *, today: date | None = None) -> list[dict[str, Any]]:
    today = today or datetime.now(UTC).date()
    out = []
    for action_type, policy in ACTION_POLICY.items():
        row = ladder_row(db, store_code, action_type)
        stats = upgrade_stats(db, store_code, action_type, today=today)
        ok, missing = upgrade_ready(stats, days_at_level=(today - _level_since(row)).days)
        out.append({"action_type": action_type, "label": policy.label, "level": row.level, "max_level": policy.max_level, "effective": effective_level(db, store_code, action_type, today=today), "history": (row.history_json or [])[-5:], "stats": stats, "upgrade_ready": ok and rank(row.level) < rank(policy.max_level), "missing": missing})
    return out


__all__ = ["ACTION_LADDER_UPGRADE", "ACTION_POLICY", "LEVELS", "SHADOW_UNTIL", "apply_upgrade", "auto_downgrade", "effective_level", "in_shadow", "ladder_row", "ladder_view", "propose_upgrades", "rank", "set_level", "upgrade_ready", "upgrade_stats"]
