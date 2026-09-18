"""D 员工(广告)的规则引擎——影子期:只出建议,落 ``amz_suggestions``,不碰亚马逊。

每条规则是"看某个窗口的数据 → 出若干 SuggestionDraft"。窗口相对 ``as_of``(该店最后一天有数据的日期,
不是今天:种子数据停在 9 月中,按今天算所有窗口都是空的;A1 接上 API 后 as_of 自然变成昨天)。

阈值来自 2026-09-15 的种子分析和外部技能库的初始默认值,以后按 SKU 从台账回看漂移(A4)。
去重:``dedupe_key = sha256(store|action_type|subject)``,每日重跑只更新 open 的那条,已决定的不再发。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from .constants import EMPLOYEE_D
from . import work_log
from .models import AmzAdSearchTerm, AmzSuggestion, AmzTransaction

WINDOW_DAYS = 60
SHORT_CAMPAIGN_DAYS = 14

HARVEST_MIN_ORDERS = 3
HARVEST_MAX_ACOS = 30.0
HARVEST_LIMIT = 8

NEGATIVE_MIN_CLICKS = 15
NEGATIVE_LIMIT = 8
HEAT_INTENT = re.compile(r"heat|hot water|warm|heiz|warmwasser|caliente|calentador|beheiz", re.I)

EXACT_INVERSION_MIN_CLICKS = 30
EXACT_INVERSION_MIN_ACOS = 80.0

LOSS_LINE_MIN_SPEND = Decimal("500")
LOSS_LINE_MIN_ACOS = 70.0

WEEK_SPEND_UP_PCT = 20.0
WEEK_SALES_DOWN_PCT = 10.0

# 产品线按活动名关键字判(A 系列没有 K 的档案;事实表落地前先这么分)。
PRODUCT_LINE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("heater", re.compile(r"热水棒|heater|immersion|bucket", re.I)),
    ("flash", re.compile(r"手电|flashlight|175|torch", re.I)),
    ("nail", re.compile(r"磨甲|nail|clipper|trimmer", re.I)),
    ("pump", re.compile(r"泵|沐浴|shower|dusche|pcs|ly-|lyq", re.I)),
)
PRODUCT_LINE_LABELS = {"pump": "沐浴泵", "heater": "热水棒", "flash": "太阳能手电", "nail": "磨甲器", "other": "其他"}

# 季节日历(自家夏季数据 + 行业经验;A4 之后由数据自己算)。(月, 日) 区间。
SEASON_CALENDAR: dict[str, dict[str, tuple[tuple[int, int], tuple[int, int]]]] = {
    "pump": {"pre": ((6, 1), (7, 19)), "peak": ((7, 20), (8, 20)), "tail": ((8, 21), (9, 30))},
    "heater": {"pre": ((10, 6), (11, 15)), "peak": ((11, 16), (2, 15)), "tail": ((2, 16), (3, 15))},
    "bundle": {"pre": ((10, 1), (10, 20)), "peak": ((10, 21), (1, 31)), "tail": ((2, 1), (2, 28))},
}
PRE_SEASON_COUNTDOWN_DAYS = 45


@dataclass
class SuggestionDraft:
    employee: str
    store_code: str
    action_type: str
    severity: str
    title: str
    why: str
    prediction: str
    subject: str
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        raw = "\x1f".join((self.store_code, self.action_type, self.subject))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def product_line_of(name: str) -> str:
    for line, pattern in PRODUCT_LINE_PATTERNS:
        if pattern.search(name or ""):
            return line
    return "other"


def _pct(numerator: Decimal | float | int, denominator: Decimal | float | int) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator) * 100, 1)


def _money(value: Decimal | float | int, currency: str) -> str:
    symbol = "€" if currency == "EUR" else "$"
    return f"{symbol}{float(value):,.0f}"


def _param(db: Session, store_code: str, name: str, default: float) -> float:
    """门槛先问经验库(参数漂移),没有就用出厂值。"""
    from .experience import param_for  # noqa: PLC0415 — experience 依赖本模块的规则函数

    return param_for(db, store_code, name, default)


def store_as_of(db: Session, store_code: str) -> date | None:
    return db.scalar(select(func.max(AmzAdSearchTerm.report_date)).where(AmzAdSearchTerm.store_code == store_code))


# ---------------------------------------------------------------- 规则


def rule_harvest_winners(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    """赢家词(≥3 单且 ACOS<30%)还没进精准组 → 收割。"""
    since = as_of - timedelta(days=WINDOW_DAYS)
    T = AmzAdSearchTerm
    rows = db.execute(
        select(
            T.search_term,
            func.sum(T.spend),
            func.sum(T.sales_7d),
            func.sum(T.orders_7d),
            func.sum(T.clicks),
            func.count(func.distinct(T.campaign_name)),
        )
        .where(T.store_code == store_code, T.report_date > since, T.report_date <= as_of)
        .group_by(T.search_term)
        .having(func.sum(T.orders_7d) >= _param(db, store_code, "harvest_min_orders", HARVEST_MIN_ORDERS))
    ).all()
    exact_targets = {
        (value or "").strip().lower()
        for value in db.scalars(
            select(T.targeting).where(T.store_code == store_code, T.match_type == "EXACT", T.report_date > since, T.report_date <= as_of).distinct()
        )
    }
    winners = []
    for term, spend, sales, orders, clicks, campaigns in rows:
        acos = _pct(spend, sales)
        if acos is None or acos >= HARVEST_MAX_ACOS:
            continue
        if term.strip().lower() in exact_targets:
            continue
        winners.append((term, Decimal(spend), Decimal(sales), int(orders), int(clicks), int(campaigns), acos))
    winners.sort(key=lambda item: item[2], reverse=True)
    drafts = []
    for term, spend, sales, orders, clicks, campaigns, acos in winners[:HARVEST_LIMIT]:
        cpc = float(spend / clicks) if clicks else 0.0
        drafts.append(
            SuggestionDraft(
                employee=EMPLOYEE_D,
                store_code=store_code,
                action_type="harvest",
                severity="warn",
                title=f"「{term}」{orders} 单 · ACOS {acos}%,还在自动/广泛组里,没进精准组",
                why=(
                    f"近 {WINDOW_DAYS} 天这个词花 {_money(spend, currency)} 卖 {_money(sales, currency)},"
                    f"散在 {campaigns} 个活动里按自动组的价在买。赢家词不收割 = 永远按别人的出价买。"
                ),
                prediction=f"建精准组、起始出价 {cpc:.2f}(该词均价)、原组加否词;14 天后该词 ACOS 应降到 {max(acos - 5, 10):.0f}% 左右,28 天看自然位。",
                subject=term.strip().lower(),
                evidence={"term": term, "spend": float(spend), "sales": float(sales), "orders": orders, "clicks": clicks, "acos_pct": acos, "campaigns": campaigns, "window_days": WINDOW_DAYS},
            )
        )
    return drafts


def rule_negatives_and_demand_reserve(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    """≥15 点击 0 单:否词;但加热意图词进「需求储备」(套装的入口),不否。"""
    since = as_of - timedelta(days=WINDOW_DAYS)
    T = AmzAdSearchTerm
    rows = db.execute(
        select(T.search_term, func.sum(T.spend), func.sum(T.clicks), func.count(func.distinct(T.campaign_name)))
        .where(T.store_code == store_code, T.report_date > since, T.report_date <= as_of, T.match_type != "EXACT")
        .group_by(T.search_term)
        .having(func.sum(T.orders_7d) == 0, func.sum(T.clicks) >= _param(db, store_code, "negative_min_clicks", NEGATIVE_MIN_CLICKS))
        .order_by(func.sum(T.spend).desc())
    ).all()
    drafts: list[SuggestionDraft] = []
    reserve: list[tuple[str, Decimal, int]] = []
    for term, spend, clicks, campaigns in rows:
        if HEAT_INTENT.search(term or ""):
            reserve.append((term, Decimal(spend), int(clicks)))
            continue
        if len([d for d in drafts if d.action_type == "negative"]) >= NEGATIVE_LIMIT:
            continue
        drafts.append(
            SuggestionDraft(
                employee=EMPLOYEE_D,
                store_code=store_code,
                action_type="negative",
                severity="info",
                title=f"「{term}」{clicks} 次点击 0 单,花了 {_money(spend, currency)}",
                why=f"近 {WINDOW_DAYS} 天在 {campaigns} 个活动里反复被匹配到,一单没有。建议在原活动加否定精准(只挡这个词,不挡它的变体)。",
                prediction="否掉后这笔花费归零;若 14 天内该词在别的组出单,自动撤回建议(需求储备逻辑)。",
                subject=term.strip().lower(),
                evidence={"term": term, "spend": float(spend), "clicks": clicks, "campaigns": campaigns, "window_days": WINDOW_DAYS},
            )
        )
    if reserve:
        total_spend = sum((item[1] for item in reserve), Decimal(0))
        total_clicks = sum(item[2] for item in reserve)
        sample = "、".join(item[0] for item in reserve[:4])
        drafts.append(
            SuggestionDraft(
                employee=EMPLOYEE_D,
                store_code=store_code,
                action_type="demand_reserve",
                severity="info",
                title=f"{len(reserve)} 个加热意图词 0 单({total_clicks} 次点击)—— 不否,转入需求储备",
                why=f"例如 {sample}。这些买家要的是带加热的套装,产品还没上;现在否掉 = 套装上市那天少一个现成入口。对泵的活动来说这是有毒流量(不转化还生产「不加热」差评)。",
                prediction="泵的活动里加否定词组挡住;套装上架时这批词自动成为推新词清单。",
                subject="heat-intent",
                evidence={"terms": [item[0] for item in reserve], "spend": float(total_spend), "clicks": total_clicks},
            )
        )
    return drafts


def rule_exact_inversion(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    """精准组里 ACOS ≥80%、≥30 点击的投放词:收词没用数据筛。"""
    since = as_of - timedelta(days=WINDOW_DAYS)
    T = AmzAdSearchTerm
    rows = db.execute(
        select(T.targeting, T.campaign_name, func.sum(T.spend), func.sum(T.sales_7d), func.sum(T.clicks), func.sum(T.orders_7d))
        .where(T.store_code == store_code, T.report_date > since, T.report_date <= as_of, T.match_type == "EXACT")
        .group_by(T.targeting, T.campaign_name)
        .having(func.sum(T.clicks) >= EXACT_INVERSION_MIN_CLICKS)
    ).all()
    drafts = []
    for target, campaign, spend, sales, clicks, orders in rows:
        acos = _pct(spend, sales)
        if sales and acos is not None and acos < EXACT_INVERSION_MIN_ACOS:
            continue
        drafts.append(
            SuggestionDraft(
                employee=EMPLOYEE_D,
                store_code=store_code,
                action_type="bid_down",
                severity="warn",
                title=f"精准词「{target}」ACOS {acos if acos is not None else '∞'}%({int(clicks)} 点击 {int(orders)} 单)",
                why=f"在活动「{campaign}」里按精准出价买,花 {_money(spend, currency)} 卖 {_money(sales, currency)}。精准组本该是最省的地方,它比自动组还贵——这个词是凭感觉放进去的。",
                prediction="出价下调 25%(护栏上限)或暂停该投放;7 天后回看该活动 ACOS。",
                subject=f"{campaign}|{(target or '').strip().lower()}",
                evidence={"target": target, "campaign": campaign, "spend": float(spend), "sales": float(sales), "clicks": int(clicks), "orders": int(orders), "acos_pct": acos},
            )
        )
    drafts.sort(key=lambda d: d.evidence["spend"], reverse=True)
    return drafts[:6]


def rule_campaign_churn(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    """两周内就没了的活动 → 数据攒不起来。一店一条。"""
    T = AmzAdSearchTerm
    rows = db.execute(
        select(T.campaign_name, func.min(T.report_date), func.max(T.report_date), func.sum(T.spend))
        .where(T.store_code == store_code)
        .group_by(T.campaign_name)
    ).all()
    short = [(name, first, last, Decimal(spend)) for name, first, last, spend in rows if (last - first).days + 1 <= SHORT_CAMPAIGN_DAYS and last < as_of - timedelta(days=7)]
    if len(short) < 3:
        return []
    spend = sum((item[3] for item in short), Decimal(0))
    return [
        SuggestionDraft(
            employee=EMPLOYEE_D,
            store_code=store_code,
            action_type="campaign_stability",
            severity="info",
            title=f"{len(short)} 个活动活了不到两周就停了,花掉 {_money(spend, currency)}",
            why=f"全店 {len(rows)} 个活动里 {len(short)} 个两周内关掉。每关一个,它攒的搜索词数据就废了;自动竞价每个活动每月要 30–50 单才跑得动。",
            prediction="新活动至少跑 30 天再判;要调的是出价和否词,不是开关活动。",
            subject="short-lived-campaigns",
            evidence={"short_campaigns": [item[0] for item in short[:12]], "count": len(short), "total_campaigns": len(rows), "spend": float(spend)},
        )
    ]


def rule_loss_line(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    """按产品线看广告账:ACOS ≥70% 且花费 ≥500 → 亏卖线,需要人决定(永远 L1)。"""
    since = as_of - timedelta(days=WINDOW_DAYS)
    T = AmzAdSearchTerm
    rows = db.execute(
        select(T.campaign_name, func.sum(T.spend), func.sum(T.sales_7d), func.sum(T.orders_7d))
        .where(T.store_code == store_code, T.report_date > since)
        .group_by(T.campaign_name)
    ).all()
    by_line: dict[str, dict[str, Decimal | int]] = {}
    for campaign, spend, sales, orders in rows:
        line = product_line_of(campaign)
        bucket = by_line.setdefault(line, {"spend": Decimal(0), "sales": Decimal(0), "orders": 0})
        bucket["spend"] += Decimal(spend)
        bucket["sales"] += Decimal(sales)
        bucket["orders"] += int(orders)
    drafts = []
    for line, bucket in by_line.items():
        acos = _pct(bucket["spend"], bucket["sales"])
        if bucket["spend"] < LOSS_LINE_MIN_SPEND or acos is None or acos < LOSS_LINE_MIN_ACOS:
            continue
        drafts.append(
            SuggestionDraft(
                employee=EMPLOYEE_D,
                store_code=store_code,
                action_type="loss_line",
                severity="bad",
                title=f"{PRODUCT_LINE_LABELS.get(line, line)}:广告 ACOS {acos}%,花 {_money(bucket['spend'], currency)} 卖 {_money(bucket['sales'], currency)}",
                why="这不是调竞价的事,是这条线的广告要不要继续投的决定。注意:广告归因亏,不等于整条线亏——自然单可能撑着;要先做增量性实验(停两周看自然单接不接得住)。",
                prediction="选项:A 降到最低保排名预算 · B 暂停全部广告两周做增量实验 · C 保持并写明理由(进经验库)。",
                subject=line,
                evidence={"product_line": line, "spend": float(bucket["spend"]), "sales": float(bucket["sales"]), "orders": int(bucket["orders"]), "acos_pct": acos},
            )
        )
    return drafts


def rule_week_spend_up_sales_down(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    """最近 7 天 vs 前 7 天:花费涨 ≥20% 且广告销售跌 ≥10% → 加广告没买来销量(德国 8 月案例)。"""
    T = AmzAdSearchTerm
    recent_since = as_of - timedelta(days=7)
    prior_since = as_of - timedelta(days=14)
    recent = db.execute(
        select(func.sum(T.spend), func.sum(T.sales_7d)).where(T.store_code == store_code, T.report_date > recent_since, T.report_date <= as_of)
    ).one()
    prior = db.execute(
        select(func.sum(T.spend), func.sum(T.sales_7d)).where(T.store_code == store_code, T.report_date > prior_since, T.report_date <= recent_since)
    ).one()
    r_spend, r_sales = Decimal(recent[0] or 0), Decimal(recent[1] or 0)
    p_spend, p_sales = Decimal(prior[0] or 0), Decimal(prior[1] or 0)
    if p_spend <= 0 or p_sales <= 0:
        return []
    spend_delta = float((r_spend - p_spend) / p_spend * 100)
    sales_delta = float((r_sales - p_sales) / p_sales * 100)
    if spend_delta < WEEK_SPEND_UP_PCT or sales_delta > -WEEK_SALES_DOWN_PCT:
        return []
    return [
        SuggestionDraft(
            employee=EMPLOYEE_D,
            store_code=store_code,
            action_type="spend_without_sales",
            severity="warn",
            title=f"最近 7 天花费 +{spend_delta:.0f}%,广告销售 {sales_delta:.0f}%",
            why=f"前 7 天花 {_money(p_spend, currency)} 卖 {_money(p_sales, currency)};最近 7 天花 {_money(r_spend, currency)} 卖 {_money(r_sales, currency)}。多花的钱没买来销量,直接从毛利里扣。",
            prediction="把最近 7 天新加的预算/出价退回到上周水位;7 天后再看。",
            subject=f"week:{as_of.isoformat()}",
            evidence={"recent_spend": float(r_spend), "recent_sales": float(r_sales), "prior_spend": float(p_spend), "prior_sales": float(p_sales), "spend_delta_pct": round(spend_delta, 1), "sales_delta_pct": round(sales_delta, 1)},
        )
    ]


def _season_start(line: str, phase: str, year: int) -> date:
    (month, day), _ = SEASON_CALENDAR[line][phase]
    return date(year, month, day)


SEASON_PHASE_LABELS = {"pre": "预热期", "peak": "旺季", "tail": "尾季", "off": "淡季"}


def season_phase_of(line: str, day: date) -> str:
    """这条产品线在这一天处于哪个季节阶段(pre/peak/tail/off)。区间可以跨年(热水棒旺季 11 月到 2 月)。"""
    phases = SEASON_CALENDAR.get(line)
    if not phases:
        return "off"
    md = (day.month, day.day)
    for phase, (start, end) in phases.items():
        inside = start <= md <= end if start <= end else (md >= start or md <= end)
        if inside:
            return phase
    return "off"


def rule_season_countdown(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    """预热期开始前 45 天内提醒:旺季前 4–6 周就要低价占位。按店里有哪些产品线判。"""
    T = AmzAdSearchTerm
    since = as_of - timedelta(days=WINDOW_DAYS)
    campaigns = db.scalars(select(T.campaign_name).where(T.store_code == store_code, T.report_date > since).distinct()).all()
    lines = {product_line_of(name) for name in campaigns}
    drafts = []
    for line in sorted(lines):
        if line not in SEASON_CALENDAR:
            continue
        for year in (as_of.year, as_of.year + 1):
            start = _season_start(line, "pre", year)
            days = (start - as_of).days
            if 0 < days <= PRE_SEASON_COUNTDOWN_DAYS:
                drafts.append(
                    SuggestionDraft(
                        employee=EMPLOYEE_D,
                        store_code=store_code,
                        action_type="season_countdown",
                        severity="info",
                        title=f"{PRODUCT_LINE_LABELS.get(line, line)}预热期 {days} 天后开始({start.isoformat()})",
                        why="旺季前 4–6 周用低出价开广告,让算法在竞争白热化之前先认相关性;这时候 CPC 最便宜。库存也要在旺季前 4–6 周到仓。",
                        prediction="预热期第一天:核心词精准组已建、预算按成熟期 1.5 倍备好、FBA 库存 ≥45 天。",
                        subject=f"{line}:{start.isoformat()}",
                        evidence={"product_line": line, "pre_season_start": start.isoformat(), "days_left": days},
                    )
                )
                break
    return drafts


RULES = (
    rule_harvest_winners,
    rule_negatives_and_demand_reserve,
    rule_exact_inversion,
    rule_campaign_churn,
    rule_loss_line,
    rule_week_spend_up_sales_down,
    rule_season_countdown,
)


# ---------------------------------------------------------------- 落库


def run_rules_for_store(db: Session, *, store_code: str, currency: str, as_of: date | None = None) -> dict[str, int]:
    """跑全部规则,upsert 到 amz_suggestions。返回计数。不 commit。"""
    as_of = as_of or store_as_of(db, store_code)
    if as_of is None:
        return {"drafts": 0, "created": 0, "updated": 0, "skipped_decided": 0}
    from .competitors import rule_competitor_changes  # noqa: PLC0415
    from .portfolio import rule_term_owner  # noqa: PLC0415
    from .rules_stock import rule_stock  # noqa: PLC0415
    from .rules_c import C_RULES  # noqa: PLC0415 — 依赖本模块的 Draft,放这里避免循环导入
    from .rules_cross import CROSS_RULES  # noqa: PLC0415

    from . import experience  # noqa: PLC0415

    drafts: list[SuggestionDraft] = []
    for rule in (*RULES, rule_stock, *CROSS_RULES, rule_term_owner, *C_RULES, rule_competitor_changes):
        drafts.extend(rule(db, store_code, currency, as_of))
    # 生成前查经验库:相关经验附在建议上;被反复驳回 / 命中率太低的那类降一档。
    # 跨店抽象层按「产品线 × 季节阶段」查:别的店在同一季节同一条线上吃过的亏,这家店不用再吃一遍。
    advice_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
    for draft in drafts:
        line = experience.line_of_subject(draft)
        phase = season_phase_of(line, as_of)
        key = (draft.action_type, line, phase)
        if key not in advice_cache:
            advice_cache[key] = experience.consult(db, store_code=store_code, action_type=draft.action_type, product_line=line, season_phase=phase)
        experience.apply_to_draft(draft, advice_cache[key])
    keys = [d.dedupe_key for d in drafts]
    existing = {
        row.dedupe_key: row
        for row in db.scalars(select(AmzSuggestion).where(AmzSuggestion.dedupe_key.in_(keys))).all()
    } if keys else {}
    created = updated = skipped = 0
    for draft in drafts:
        row = existing.get(draft.dedupe_key)
        if row is None:
            row = AmzSuggestion(
                    employee=draft.employee,
                    store_code=draft.store_code,
                    action_type=draft.action_type,
                    severity=draft.severity,
                    title=draft.title[:512],
                    why=draft.why,
                    prediction=draft.prediction,
                    evidence_json=draft.evidence,
                    level="L0",
                    status="open",
                    dedupe_key=draft.dedupe_key,
                    as_of=as_of,
                )
            db.add(row)
            db.flush()
            # 硬记忆:她提过什么、为什么,从提出的那一刻就在日志里。
            work_log.record(
                db,
                employee=draft.employee,
                kind="suggested",
                title=draft.title[:512],
                why=draft.why,
                store_code=draft.store_code,
                subject=draft.subject,
                detail={"action_type": draft.action_type, "severity": draft.severity, "prediction": draft.prediction, "as_of": as_of.isoformat()},
                source="rule",
                suggestion_id=row.id,
            )
            created += 1
        elif row.status == "open":
            row.title = draft.title[:512]
            row.why = draft.why
            row.prediction = draft.prediction
            row.evidence_json = draft.evidence
            row.severity = draft.severity
            row.as_of = as_of
            db.add(row)
            updated += 1
        else:
            skipped += 1
    db.flush()
    return {"drafts": len(drafts), "created": created, "updated": updated, "skipped_decided": skipped}


__all__ = ["SEASON_PHASE_LABELS", "season_phase_of", "RULES", "SuggestionDraft", "product_line_of", "run_rules_for_store", "store_as_of", "PRODUCT_LINE_LABELS", "SEASON_CALENDAR"]
