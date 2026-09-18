"""A4 经验库:系统怎么越用越聪明。

三条进料:
1. **结果**(amz_outcomes):每条建议 14 / 28 天后对不对。影子期没有真执行,也能判——「收割」说这个词是赢家,28 天后它还在出单、ACOS 还低,就是说对了;
   「否词」说这个词烧钱不出单,28 天后它还是 0 单,就是说对了。数据还不够新的时候用**回测**:把规则放回过去某天跑,看之后发生了什么。
2. **决定**:人驳回时必填的那句原因。某店某类建议被驳回得多,就降一档严重度并把原因带在下一条建议上。
3. **图片回看**:换图前后的点击率。

两种产出(amz_experience):
- **经验条目**:一句人话 + 证据 + 样本数。建议生成前 ``consult()`` 查一遍,把相关经验附在建议上;员工聊天时也能读到。
- **参数漂移**:某店某条规则命中率太低 → 那家店的门槛抬一档(有上限,永不低于出厂值);命中率回来了再放回去。

阈值保守:样本 <6 不下结论;漂移每次一档;全部可在库里看到、可退休(status=retired)。不 commit。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .constants import EMPLOYEE_A, EMPLOYEE_B, EMPLOYEE_C, EMPLOYEE_D
from .models import AmzAdSearchTerm, AmzExperience, AmzImageBrief, AmzOutcome, AmzStore, AmzSuggestion

_LOGGER = logging.getLogger("amz.experience")

HORIZONS = (14, 28)
MIN_SAMPLES = 6
BACKTEST_POINTS = 3
BACKTEST_STEP_DAYS = 14

ACTION_LABELS = {"harvest": "收割赢家词", "negative": "否词", "bid_down": "精准倒挂降价", "screen_ctr_gap": "同屏输了", "listing_cvr_gap": "页面接不住词"}
ACTION_EMPLOYEE = {"harvest": EMPLOYEE_D, "negative": EMPLOYEE_D, "bid_down": EMPLOYEE_D, "screen_ctr_gap": EMPLOYEE_B, "listing_cvr_gap": EMPLOYEE_A, "image": EMPLOYEE_B}

# 参数漂移:名字 → (出厂值, 每档步长, 上限, 由哪个 action 的命中率驱动, 低于多少抬, 高于多少放)
PARAMS: dict[str, tuple[float, float, float, str, float, float]] = {
    "harvest_min_orders": (3, 1, 5, "harvest", 50.0, 85.0),
    "negative_min_clicks": (15, 5, 30, "negative", 60.0, 90.0),
}

REJECTION_MIN_DECISIONS = 5
REJECTION_RATE_PCT = 70.0


# ---------------------------------------------------------------- 结果判定(纯函数 + 取数)


@dataclass
class Window:
    clicks: int
    orders: int
    spend: Decimal
    sales: Decimal

    @property
    def acos(self) -> float | None:
        return float(self.spend / self.sales * 100) if self.sales else None


def _term_window(db: Session, *, store_code: str, term: str, start: date, end: date) -> Window:
    T = AmzAdSearchTerm
    row = db.execute(
        select(func.sum(T.clicks), func.sum(T.orders_7d), func.sum(T.spend), func.sum(T.sales_7d)).where(
            T.store_code == store_code, func.lower(func.trim(T.search_term)) == term.lower().strip(), T.report_date > start, T.report_date <= end
        )
    ).one()
    return Window(int(row[0] or 0), int(row[1] or 0), Decimal(row[2] or 0), Decimal(row[3] or 0))


def _target_window(db: Session, *, store_code: str, campaign: str, target: str, start: date, end: date) -> Window:
    T = AmzAdSearchTerm
    row = db.execute(
        select(func.sum(T.clicks), func.sum(T.orders_7d), func.sum(T.spend), func.sum(T.sales_7d)).where(
            T.store_code == store_code, T.campaign_name == campaign, func.lower(func.trim(T.targeting)) == target.lower().strip(), T.match_type == "EXACT", T.report_date > start, T.report_date <= end
        )
    ).one()
    return Window(int(row[0] or 0), int(row[1] or 0), Decimal(row[2] or 0), Decimal(row[3] or 0))


def judge(action_type: str, window: Window) -> str:
    """right / wrong / na。宁可 na 也不硬判——样本太小的窗口不算数。"""
    if action_type == "harvest":
        if window.clicks < 5:
            return "na"
        return "right" if window.orders >= 1 and (window.acos is None or window.acos < 40.0) else "wrong"
    if action_type == "negative":
        if window.clicks < 5:
            return "na"
        return "right" if window.orders == 0 else "wrong"
    if action_type == "bid_down":
        if window.clicks < 10:
            return "na"
        return "right" if window.acos is None or window.acos >= 60.0 else "wrong"
    return "na"


def data_range(db: Session, store_code: str) -> tuple[date | None, date | None]:
    T = AmzAdSearchTerm
    row = db.execute(select(func.min(T.report_date), func.max(T.report_date)).where(T.store_code == store_code)).one()
    return row[0], row[1]


def _window_for(db: Session, *, store_code: str, action_type: str, evidence: dict[str, Any], subject: str, start: date, end: date) -> Window | None:
    if action_type in ("harvest", "negative"):
        term = str(evidence.get("term") or subject)
        return _term_window(db, store_code=store_code, term=term, start=start, end=end) if term else None
    if action_type == "bid_down":
        campaign, target = str(evidence.get("campaign") or ""), str(evidence.get("target") or "")
        if not campaign or not target:
            return None
        return _target_window(db, store_code=store_code, campaign=campaign, target=target, start=start, end=end)
    return None


def _upsert_outcome(db: Session, *, store_code: str, action_type: str, subject: str, as_of: date, horizon: int, source: str, verdict: str, metrics: dict[str, Any], suggestion_id: Any = None) -> None:
    stmt = pg_insert(AmzOutcome).values(store_code=store_code, action_type=action_type, subject=subject[:255], as_of=as_of, horizon_days=horizon, source=source, verdict=verdict, metrics_json=metrics, suggestion_id=suggestion_id)
    db.execute(stmt.on_conflict_do_update(constraint="uq_amz_outcomes_key", set_={"verdict": verdict, "metrics": metrics}))


def evaluate_live(db: Session, store_code: str) -> int:
    """真实建议:as_of + horizon 已经有数据的,判一次。"""
    _, last = data_range(db, store_code)
    if last is None:
        return 0
    n = 0
    rows = db.scalars(select(AmzSuggestion).where(AmzSuggestion.store_code == store_code, AmzSuggestion.action_type.in_(("harvest", "negative", "bid_down")), AmzSuggestion.as_of.is_not(None)))
    for row in rows:
        for horizon in HORIZONS:
            if row.as_of + timedelta(days=horizon) > last:
                continue
            window = _window_for(db, store_code=store_code, action_type=row.action_type, evidence=row.evidence_json or {}, subject="", start=row.as_of, end=row.as_of + timedelta(days=horizon))
            if window is None:
                continue
            _upsert_outcome(db, store_code=store_code, action_type=row.action_type, subject=row.dedupe_key, as_of=row.as_of, horizon=horizon, source="live", verdict=judge(row.action_type, window), metrics={"clicks": window.clicks, "orders": window.orders, "acos_pct": window.acos, "decision": row.status}, suggestion_id=row.id)
            n += 1
    return n


def backtest(db: Session, store: AmzStore) -> int:
    """把三条可判的规则放回过去的几个时点跑,看之后发生了什么。只读规则函数,不落建议。"""
    from . import rules  # noqa: PLC0415

    first, last = data_range(db, store.store_code)
    if first is None or last is None:
        return 0
    n = 0
    for k in range(BACKTEST_POINTS):
        as_of = last - timedelta(days=max(HORIZONS) + k * BACKTEST_STEP_DAYS)
        if as_of - timedelta(days=21) < first:  # 至少三周历史才有意义
            break
        drafts = []
        for rule in (rules.rule_harvest_winners, rules.rule_negatives_and_demand_reserve, rules.rule_exact_inversion):
            drafts.extend(rule(db, store.store_code, store.currency, as_of))
        for draft in drafts:
            if draft.action_type not in ("harvest", "negative", "bid_down"):
                continue
            for horizon in HORIZONS:
                window = _window_for(db, store_code=store.store_code, action_type=draft.action_type, evidence=draft.evidence, subject=draft.subject, start=as_of, end=as_of + timedelta(days=horizon))
                if window is None:
                    continue
                _upsert_outcome(db, store_code=store.store_code, action_type=draft.action_type, subject=draft.subject, as_of=as_of, horizon=horizon, source="backtest", verdict=judge(draft.action_type, window), metrics={"clicks": window.clicks, "orders": window.orders, "acos_pct": window.acos, "title": draft.title[:160]})
                n += 1
    return n


# ---------------------------------------------------------------- 条目


def _upsert_entry(db: Session, *, key: str, scope: str, store_code: str | None, action_type: str, kind: str, statement: str, evidence: dict[str, Any], samples: int, hits: int, value: float | None) -> None:
    stmt = pg_insert(AmzExperience).values(entry_key=key, scope=scope, store_code=store_code, action_type=action_type, kind=kind, employee=ACTION_EMPLOYEE.get(action_type), statement=statement, evidence_json=evidence, samples=samples, hits=hits, value=value, status="active")
    db.execute(stmt.on_conflict_do_update(constraint="uq_amz_experience_key", set_={"statement": statement, "evidence": evidence, "samples": samples, "hits": hits, "value": value, "updated_at": func.now()}))


def precision_rows(db: Session, *, store_code: str | None, horizon: int = 28) -> list[tuple[str, int, int]]:
    """[(action_type, right, wrong)]。live 与 backtest 合并(同键 live 优先已在唯一键里分开,这里都算)。"""
    O = AmzOutcome
    q = select(O.action_type, O.verdict, func.count()).where(O.horizon_days == horizon, O.verdict.in_(("right", "wrong"))).group_by(O.action_type, O.verdict)
    if store_code is not None:
        q = q.where(O.store_code == store_code)
    tally: dict[str, dict[str, int]] = {}
    for action, verdict, count in db.execute(q).all():
        tally.setdefault(action, {"right": 0, "wrong": 0})[verdict] = int(count)
    return [(a, t["right"], t["wrong"]) for a, t in sorted(tally.items())]


def drift_value(current: float, *, default: float, step: float, cap: float, precision: float, low: float, high: float) -> float:
    """一次一档;低于 low 抬、高于 high 放;永不低于出厂值、不超上限。"""
    if precision < low:
        return min(cap, current + step)
    if precision >= high and current > default:
        return max(default, current - step)
    return current


def learn_precision_and_params(db: Session, store_code: str) -> int:
    n = 0
    for action, right, wrong in precision_rows(db, store_code=store_code):
        total = right + wrong
        if total < MIN_SAMPLES:
            continue
        pct = round(right / total * 100, 1)
        label = ACTION_LABELS.get(action, action)
        _upsert_entry(db, key=f"store|{store_code}|{action}|precision", scope="store", store_code=store_code, action_type=action, kind="precision", statement=f"{store_code} 的「{label}」建议,28 天后回头看:{total} 条里 {right} 条成立({pct}%)。", evidence={"right": right, "wrong": wrong, "horizon_days": 28}, samples=total, hits=right, value=pct)
        n += 1
        for name, (default, step, cap, driver, low, high) in PARAMS.items():
            if driver != action:
                continue
            current = param_for(db, store_code, name, default)
            new = drift_value(current, default=default, step=step, cap=cap, precision=pct, low=low, high=high)
            if new != current or new != default:
                direction = "抬到" if new > current else ("放回" if new < current else "维持在")
                _upsert_entry(db, key=f"store|{store_code}|{name}|param", scope="store", store_code=store_code, action_type=action, kind="param", statement=f"{store_code} 的「{label}」命中率 {pct}%({total} 条),门槛 {name} {direction} {new:g}(出厂 {default:g})。", evidence={"precision_pct": pct, "samples": total, "default": default, "previous": current}, samples=total, hits=right, value=new)
                n += 1
    return n


def learn_global(db: Session) -> int:
    n = 0
    for action, right, wrong in precision_rows(db, store_code=None):
        total = right + wrong
        stores = db.scalar(select(func.count(func.distinct(AmzOutcome.store_code))).where(AmzOutcome.action_type == action, AmzOutcome.horizon_days == 28, AmzOutcome.verdict.in_(("right", "wrong"))))
        if total < MIN_SAMPLES * 2 or int(stores or 0) < 2:
            continue
        pct = round(right / total * 100, 1)
        _upsert_entry(db, key=f"global|{action}|precision", scope="global", store_code=None, action_type=action, kind="precision", statement=f"跨 {stores} 家店,「{ACTION_LABELS.get(action, action)}」建议 28 天后成立 {right}/{total}({pct}%)。", evidence={"right": right, "wrong": wrong, "stores": int(stores or 0)}, samples=total, hits=right, value=pct)
        n += 1
    return n


ABSTRACT_MIN_SAMPLES = 6
ABSTRACT_GAP_PCT = 15.0  # 比这类建议的全局命中率低/高这么多,才值得写成一条抽象经验


def line_of_subject(draft_or_subject: Any) -> str:
    """建议 / 结果 → 产品线。证据里写了就用;否则按搜索词认(买家的话);认不出再按 SKU/活动名认。"""
    from .ba_competitors import line_of_term  # noqa: PLC0415
    from .rules import product_line_of  # noqa: PLC0415

    evidence = getattr(draft_or_subject, "evidence", None) or getattr(draft_or_subject, "metrics_json", None) or {}
    line = evidence.get("product_line") if isinstance(evidence, dict) else None
    if line:
        return str(line)
    subject = getattr(draft_or_subject, "subject", draft_or_subject)
    text = str(subject or "")
    term = text.split("|")[-1] if "|" in text else text
    return line_of_term(term) or product_line_of(text)


def learn_abstract(db: Session) -> int:
    """跨店抽象层:把所有店的 28 天结果按(动作 × 产品线 × 季节阶段)归纳,和这类动作的全局命中率比。

    只在「至少两家店、样本够、和全局差得明显」时写一条——那才是能搬到别的店用的规律,
    比如「旺季里泵线的否词建议跨 3 店只成立 30%(全局 62%):旺季流量宽,别急着否」。
    """
    from .rules import PRODUCT_LINE_LABELS, SEASON_PHASE_LABELS, season_phase_of  # noqa: PLC0415

    rows = db.scalars(select(AmzOutcome).where(AmzOutcome.horizon_days == 28, AmzOutcome.verdict.in_(("right", "wrong"))))
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    overall: dict[str, list[int]] = {}
    for o in rows:
        line = line_of_subject(o)
        phase = season_phase_of(line, o.as_of)
        g = groups.setdefault((o.action_type, line, phase), {"right": 0, "wrong": 0, "stores": set()})
        g["right" if o.verdict == "right" else "wrong"] += 1
        g["stores"].add(o.store_code)
        tally = overall.setdefault(o.action_type, [0, 0])
        tally[0 if o.verdict == "right" else 1] += 1
    n = 0
    for (action, line, phase), g in groups.items():
        total = g["right"] + g["wrong"]
        if total < ABSTRACT_MIN_SAMPLES or len(g["stores"]) < 2 or line == "other":
            continue
        pct = round(g["right"] / total * 100, 1)
        base_right, base_wrong = overall[action]
        base = round(base_right / (base_right + base_wrong) * 100, 1)
        if abs(pct - base) < ABSTRACT_GAP_PCT:
            continue
        label = ACTION_LABELS.get(action, action)
        where = f"{SEASON_PHASE_LABELS.get(phase, phase)} · {PRODUCT_LINE_LABELS.get(line, line)}"
        verdict = "明显更不靠谱,这个阶段先别急着做" if pct < base else "明显更靠谱,这个阶段可以更果断"
        _upsert_entry(
            db,
            key=f"abstract|{action}|{line}|{phase}",
            scope="abstract",
            store_code=None,
            action_type=action,
            kind="precision",
            statement=f"{where}:「{label}」跨 {len(g['stores'])} 家店 28 天后成立 {g['right']}/{total}({pct}%),全局 {base}%——{verdict}。",
            evidence={"product_line": line, "season_phase": phase, "right": g["right"], "wrong": g["wrong"], "stores": sorted(g["stores"]), "global_pct": base},
            samples=total,
            hits=g["right"],
            value=pct,
        )
        n += 1
    return n


def learn_from_decisions(db: Session, store_code: str) -> int:
    S = AmzSuggestion
    n = 0
    rows = db.execute(select(S.action_type, S.status, func.count()).where(S.store_code == store_code, S.status.in_(("approved", "rejected"))).group_by(S.action_type, S.status)).all()
    tally: dict[str, dict[str, int]] = {}
    for action, status, count in rows:
        tally.setdefault(action, {"approved": 0, "rejected": 0})[status] = int(count)
    for action, t in tally.items():
        total = t["approved"] + t["rejected"]
        if total < REJECTION_MIN_DECISIONS:
            continue
        rate = round(t["rejected"] / total * 100, 1)
        if rate < REJECTION_RATE_PCT:
            continue
        reasons = [r for r in db.scalars(select(S.reject_reason).where(S.store_code == store_code, S.action_type == action, S.status == "rejected", S.reject_reason.is_not(None)).order_by(S.decided_at.desc()).limit(3)) if r]
        _upsert_entry(db, key=f"store|{store_code}|{action}|rejection", scope="store", store_code=store_code, action_type=action, kind="rejection", statement=f"{store_code} 的「{ACTION_LABELS.get(action, action)}」建议,人决定过 {total} 条,驳回 {t['rejected']} 条({rate}%)。最近的原因:{';'.join(reasons) or '(没写)'}", evidence={"approved": t["approved"], "rejected": t["rejected"], "reasons": reasons}, samples=total, hits=t["rejected"], value=rate)
        n += 1
    return n


def learn_from_images(db: Session, store_code: str) -> int:
    n = 0
    for brief in db.scalars(select(AmzImageBrief).where(AmzImageBrief.store_code == store_code, AmzImageBrief.status == "live")):
        d28 = (brief.lookback_json or {}).get("d28")
        if not d28 or d28.get("ads_ctr_delta_points") is None:
            continue
        delta = float(d28["ads_ctr_delta_points"])
        term = (brief.baseline_json or {}).get("term")
        _upsert_entry(db, key=f"store|{store_code}|image|{brief.id}", scope="store", store_code=store_code, action_type="image", kind="image", statement=f"{store_code} 换{brief.position}图({brief.title}):「{term}」的点击率 28 天{'涨' if delta > 0 else '掉'}了 {abs(delta):.2f} 个点。", evidence={"brief_id": str(brief.id), **d28}, samples=1, hits=1 if delta > 0 else 0, value=delta)
        n += 1
    return n


def refresh_store(db: Session, store: AmzStore) -> dict[str, int]:
    out = {"live_outcomes": evaluate_live(db, store.store_code), "backtest_outcomes": backtest(db, store)}
    db.flush()
    out["entries"] = learn_precision_and_params(db, store.store_code) + learn_from_decisions(db, store.store_code) + learn_from_images(db, store.store_code) + learn_global(db) + learn_abstract(db)
    db.flush()
    return out


# ---------------------------------------------------------------- 给规则引擎和员工用


def param_for(db: Session, store_code: str, name: str, default: float) -> float:
    row = db.scalar(select(AmzExperience.value).where(AmzExperience.entry_key == f"store|{store_code}|{name}|param", AmzExperience.status == "active"))
    return float(row) if row is not None else float(default)


def consult(db: Session, *, store_code: str, action_type: str, product_line: str | None = None, season_phase: str | None = None) -> dict[str, Any]:
    """生成建议前查一遍:相关经验的句子 + 是否该降一档严重度。

    顺序:本店 → 同产品线同季节阶段的跨店抽象经验 → 全局。抽象经验说「这个阶段明显不靠谱」也降一档。
    """
    rows = list(db.scalars(select(AmzExperience).where(AmzExperience.status == "active", AmzExperience.action_type == action_type, (AmzExperience.store_code == store_code) | (AmzExperience.scope == "global")).order_by(AmzExperience.scope.desc())))
    abstract = None
    if product_line and season_phase:
        abstract = db.scalar(select(AmzExperience).where(AmzExperience.status == "active", AmzExperience.entry_key == f"abstract|{action_type}|{product_line}|{season_phase}"))
    store_rows = [r for r in rows if r.scope != "global"]
    global_rows = [r for r in rows if r.scope == "global"]
    ordered = store_rows + ([abstract] if abstract is not None else []) + global_rows
    notes = [r.statement for r in ordered][:3]
    downgrade = any(r.kind == "rejection" for r in rows) or any(r.kind == "precision" and r.scope == "store" and r.value is not None and float(r.value) < 40.0 for r in rows)
    if abstract is not None and abstract.value is not None and float(abstract.value) < float((abstract.evidence_json or {}).get("global_pct") or 0):
        downgrade = True
    return {"notes": notes, "downgrade": downgrade}


SEVERITY_DOWN = {"bad": "warn", "warn": "info", "info": "info", "good": "good"}


def apply_to_draft(draft: Any, advice: dict[str, Any]) -> None:
    if advice["notes"]:
        draft.evidence = {**draft.evidence, "experience": advice["notes"]}
    if advice["downgrade"]:
        draft.severity = SEVERITY_DOWN.get(draft.severity, draft.severity)
        draft.evidence = {**draft.evidence, "experience_downgraded": True}


def list_entries(db: Session, *, store_codes: list[str] | None, employee: str | None = None, limit: int = 100) -> list[AmzExperience]:
    q = select(AmzExperience).where(AmzExperience.status == "active")
    if employee:
        q = q.where(AmzExperience.employee == employee.upper())
    rows = list(db.scalars(q.order_by(AmzExperience.updated_at.desc()).limit(limit * 3)))
    if store_codes is not None:
        rows = [r for r in rows if r.store_code is None or r.store_code in store_codes]
    return rows[:limit]


def view(row: AmzExperience) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "scope": row.scope,
        "store_code": row.store_code,
        "action_type": row.action_type,
        "action_label": ACTION_LABELS.get(row.action_type, "图片" if row.action_type == "image" else row.action_type),
        "kind": row.kind,
        "employee": row.employee,
        "statement": row.statement,
        "evidence": row.evidence_json or {},
        "samples": row.samples,
        "hits": row.hits,
        "value": float(row.value) if row.value is not None else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


__all__ = ["ACTION_LABELS", "learn_abstract", "line_of_subject", "HORIZONS", "MIN_SAMPLES", "PARAMS", "Window", "apply_to_draft", "backtest", "consult", "data_range", "drift_value", "evaluate_live", "judge", "learn_from_decisions", "learn_from_images", "learn_global", "learn_precision_and_params", "list_entries", "param_for", "precision_rows", "refresh_store", "view"]
