"""C 殷长辰的规则:搜索词表现(SQP)——只报变化,事实和判断分开。

数据:amz_sqp,按周 × ASIN × 搜索词,四个份额(曝光 / 点击 / 加购 / 购买 = 我们 ÷ 全市场)。
两条规则,都比「上周 vs 上上周」:
1. **详情页在漏**:点击份额明显高于购买份额(人点进来了没买)——转给笑笑(文案 / 价格)和熊(图片);
2. **份额掉了**:购买份额或点击份额环比掉三成以上且词有量——报出来,并说清是曝光没了(词没接住)还是点击没了(同屏输了)。
外加每店每周**一句话简报**(info):哪些词涨、哪些词掉,给老板看一眼就够。

阈值取自外部技能库的初始默认值与种子经验,A4 之后按台账回看漂移。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .constants import EMPLOYEE_C
from .models import AmzSqp
from .rules import SuggestionDraft

LEAK_MIN_CLICKS = 10          # 我们上周在这个词上至少拿到的点击
LEAK_RATIO = 2.0              # 点击份额 ≥ 购买份额 × 2 才叫漏
LEAK_MIN_CLICK_SHARE = 1.0    # 点击份额至少 1%,否则是噪声
LEAK_LIMIT = 5

DROP_MIN_VOLUME = 500         # 全市场曝光量门槛
DROP_REL_PCT = 30.0           # 环比掉三成
DROP_MIN_ABS_POINTS = 0.5     # 且绝对掉 0.5 个百分点
DROP_LIMIT = 5

ACTION_DETAIL_PAGE_LEAK = "sqp_detail_page_leak"
ACTION_SHARE_DROP = "sqp_share_drop"
ACTION_WEEKLY_BRIEF = "sqp_weekly_brief"


@dataclass
class Week:
    start: date
    rows: dict[tuple[str, str], AmzSqp]  # (asin, query) → row


def _f(value: Decimal | None) -> float:
    return float(value) if value is not None else 0.0


def load_weeks(db: Session, store_code: str) -> tuple[Week | None, Week | None]:
    """最近两个有数据的周(新的在前)。"""
    starts = list(db.scalars(select(AmzSqp.period_start).where(AmzSqp.store_code == store_code).distinct().order_by(AmzSqp.period_start.desc()).limit(2)))
    if not starts:
        return None, None
    weeks: list[Week] = []
    for start in starts:
        rows = {(r.asin, r.search_query): r for r in db.scalars(select(AmzSqp).where(AmzSqp.store_code == store_code, AmzSqp.period_start == start))}
        weeks.append(Week(start=start, rows=rows))
    return weeks[0], (weeks[1] if len(weeks) > 1 else None)


def rule_detail_page_leak(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    latest, _ = load_weeks(db, store_code)
    if latest is None:
        return []
    found = []
    for (asin, query), r in latest.rows.items():
        clicks, buys = _f(r.clicks_share_pct), _f(r.purchases_share_pct)
        if (r.clicks_asin or 0) < LEAK_MIN_CLICKS or clicks < LEAK_MIN_CLICK_SHARE:
            continue
        if clicks >= max(buys, 0.01) * LEAK_RATIO:
            found.append((r, clicks, buys))
    found.sort(key=lambda t: -(t[0].clicks_asin or 0))
    drafts = []
    for r, clicks, buys in found[:LEAK_LIMIT]:
        drafts.append(
            SuggestionDraft(
                employee=EMPLOYEE_C,
                store_code=store_code,
                action_type=ACTION_DETAIL_PAGE_LEAK,
                severity="warn",
                title=f"「{r.search_query}」{r.asin}:点击份额 {clicks:.1f}%,购买份额只有 {buys:.1f}%——人点进来了没买,详情页在漏",
                why=(
                    f"事实:{latest.start.isoformat()} 起那一周,这个词全市场曝光 {r.impressions_total},我们拿到 {r.clicks_asin} 次点击"
                    f"(点击份额 {clicks:.1f}%),购买份额 {buys:.1f}%。判断:搜索页赢了、详情页输了——价格、图、五点、评论里至少一样接不住这个词的人。"
                ),
                prediction="建议:转给笑笑对照标题/五点和价格,转给殷熊看主图与副图;改后看下一周购买份额是否向点击份额靠拢。",
                subject=f"{r.asin}|{r.search_query}|{latest.start.isoformat()}",
                evidence={
                    "asin": r.asin,
                    "query": r.search_query,
                    "week_start": latest.start.isoformat(),
                    "impressions_total": r.impressions_total,
                    "clicks_asin": r.clicks_asin,
                    "clicks_share_pct": clicks,
                    "cart_adds_share_pct": _f(r.cart_adds_share_pct),
                    "purchases_share_pct": buys,
                    "handoff": ["A", "B"],
                },
            )
        )
    return drafts


def rule_share_drop(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    latest, prior = load_weeks(db, store_code)
    if latest is None or prior is None:
        return []
    drops = []
    for key, now in latest.rows.items():
        before = prior.rows.get(key)
        if before is None or (now.impressions_total or 0) < DROP_MIN_VOLUME:
            continue
        for metric, label in (("purchases_share_pct", "购买份额"), ("clicks_share_pct", "点击份额")):
            a, b = _f(getattr(before, metric)), _f(getattr(now, metric))
            if a <= 0:
                continue
            rel = (a - b) / a * 100
            if rel >= DROP_REL_PCT and (a - b) >= DROP_MIN_ABS_POINTS:
                drops.append((now, before, metric, label, a, b, rel))
                break  # 一个词一条
    drops.sort(key=lambda t: -(t[1].purchases_asin or 0))
    drafts = []
    for now, before, metric, label, a, b, rel in drops[:DROP_LIMIT]:
        imp_before, imp_now = _f(before.impressions_share_pct), _f(now.impressions_share_pct)
        if imp_before > 0 and (imp_before - imp_now) / imp_before * 100 >= DROP_REL_PCT:
            cause = "曝光份额一起掉了——词没接住(标题 / 后台词 / 广告位),先找笑笑和素素"
        elif metric == "purchases_share_pct" and _f(now.clicks_share_pct) >= _f(before.clicks_share_pct) * 0.8:
            cause = "点击还在、购买掉了——详情页或价格出了变化,对手可能降价或上了 coupon,先看竞品价格"
        else:
            cause = "曝光还在、点击掉了——搜索页同屏输了,先找殷熊看主图"
        drafts.append(
            SuggestionDraft(
                employee=EMPLOYEE_C,
                store_code=store_code,
                action_type=ACTION_SHARE_DROP,
                severity="warn" if metric == "purchases_share_pct" else "info",
                title=f"「{now.search_query}」{now.asin}:{label}从 {a:.1f}% 掉到 {b:.1f}%(环比 −{rel:.0f}%)",
                why=(
                    f"事实:{prior.start.isoformat()} 那周{label} {a:.1f}%,{latest.start.isoformat()} 那周 {b:.1f}%;"
                    f"全市场曝光 {before.impressions_total} → {now.impressions_total}。判断:{cause}。"
                ),
                prediction="建议:先看清楚再动;下一周再掉一次就要动手,连续两周回升就当噪声。",
                subject=f"{now.asin}|{now.search_query}|{latest.start.isoformat()}|{metric}",
                evidence={
                    "asin": now.asin,
                    "query": now.search_query,
                    "metric": metric,
                    "weeks": [prior.start.isoformat(), latest.start.isoformat()],
                    "before_pct": a,
                    "after_pct": b,
                    "rel_drop_pct": round(rel, 1),
                    "impressions_total": [before.impressions_total, now.impressions_total],
                    "impressions_share_pct": [imp_before, imp_now],
                },
            )
        )
    return drafts


def rule_weekly_brief(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    """每店每周一条 info:上周 SQP 一句话——涨的、掉的、总盘。"""
    latest, prior = load_weeks(db, store_code)
    if latest is None:
        return []
    by_asin: dict[str, list[AmzSqp]] = defaultdict(list)
    for (asin, _), r in latest.rows.items():
        by_asin[asin].append(r)
    parts = []
    ups, downs = [], []
    for asin, rows in by_asin.items():
        clicks = sum(r.clicks_asin or 0 for r in rows)
        buys = sum(r.purchases_asin or 0 for r in rows)
        parts.append(f"{asin} 上了 {len(rows)} 个词、拿到 {clicks} 次点击 {buys} 单")
        if prior is not None:
            for r in rows:
                b = prior.rows.get((asin, r.search_query))
                if b is None or (r.impressions_total or 0) < DROP_MIN_VOLUME:
                    continue
                d = _f(r.purchases_share_pct) - _f(b.purchases_share_pct)
                if d >= 1.0:
                    ups.append(f"{r.search_query}(+{d:.1f} 点)")
                elif d <= -1.0:
                    downs.append(f"{r.search_query}({d:.1f} 点)")
    ups.sort()
    downs.sort()
    summary = ";".join(parts)
    movement = ""
    if prior is not None:
        movement = f" 购买份额涨的:{'、'.join(ups[:4]) or '没有'};掉的:{'、'.join(downs[:4]) or '没有'}。"
    else:
        movement = " 只有这一周的数据,下周开始能比变化。"
    return [
        SuggestionDraft(
            employee=EMPLOYEE_C,
            store_code=store_code,
            action_type=ACTION_WEEKLY_BRIEF,
            severity="info",
            title=f"{latest.start.isoformat()} 起那一周的搜索词表现:{summary}",
            why=f"事实:{summary}。{movement}",
            prediction="判断和建议见同周的「详情页在漏」「份额掉了」两类条目;没有就是这周没什么要动的。",
            subject=f"brief|{latest.start.isoformat()}",
            evidence={"week_start": latest.start.isoformat(), "asins": sorted(by_asin), "ups": ups[:10], "downs": downs[:10]},
        )
    ]


C_RULES = (rule_detail_page_leak, rule_share_drop, rule_weekly_brief)

__all__ = ["ACTION_DETAIL_PAGE_LEAK", "ACTION_SHARE_DROP", "ACTION_WEEKLY_BRIEF", "C_RULES", "load_weeks", "rule_detail_page_leak", "rule_share_drop", "rule_weekly_brief"]
