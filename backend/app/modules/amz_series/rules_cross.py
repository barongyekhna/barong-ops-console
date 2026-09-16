"""跨店对照规则(A 殷笑笑 / B 殷熊):同一个搜索词、同一款货、几家店谁接得住。

三店同款(01us / 03us / 04us 的泵是同一批货)是天然的 A/B 场:
- 同词点击进来了、别家转化好、我们不转化 → 页面接不住这个词 → 笑笑的活(标题 / 五点 / 价格对照)
- 同词曝光量够、别家点击率高、我们没人点 → 搜索页同屏输了 → 熊的活(主图 / 标题前 80 字符)

只在同币种(同市场)的兄弟店之间比,德国站不跟美国站比。每天随该店的 rules_daily 一起跑,
只给「这家店」出草稿;兄弟店各自跑自己的那份。阈值先取种子分析的经验值,A4 之后按台账回看漂移。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .constants import EMPLOYEE_A, EMPLOYEE_B
from .models import AmzAdSearchTerm, AmzStore
from .rules import PRODUCT_LINE_LABELS, WINDOW_DAYS, SuggestionDraft, product_line_of

CVR_MIN_CLICKS = 20
CVR_BEST_MIN_ORDERS = 3
CVR_GAP_RATIO = 0.5
CVR_LIMIT = 6
CVR_WARN_CLICKS = 50

CTR_MIN_IMPRESSIONS = 500
CTR_BEST_MIN_CLICKS = 10
CTR_GAP_RATIO = 0.5
CTR_LIMIT = 4

ACTION_LISTING_CVR_GAP = "listing_cvr_gap"
ACTION_SCREEN_CTR_GAP = "screen_ctr_gap"


@dataclass
class TermStat:
    store_code: str
    term: str
    impressions: int
    clicks: int
    orders: int
    spend: Decimal
    sales: Decimal
    campaign: str

    @property
    def ctr(self) -> float:
        return self.clicks / self.impressions * 100 if self.impressions else 0.0

    @property
    def cvr(self) -> float:
        return self.orders / self.clicks * 100 if self.clicks else 0.0

    @property
    def line(self) -> str:
        return product_line_of(self.campaign)


def sibling_stores(db: Session, store_code: str, currency: str) -> list[str]:
    return list(
        db.scalars(
            select(AmzStore.store_code).where(
                AmzStore.currency == currency, AmzStore.store_code != store_code, AmzStore.status == "active"
            )
        )
    )


def term_stats(db: Session, *, store_codes: list[str], currency: str, since: date) -> dict[str, dict[str, TermStat]]:
    """{term: {store: TermStat}},词按小写去空格归一。"""
    T = AmzAdSearchTerm
    rows = db.execute(
        select(
            T.store_code,
            func.lower(func.trim(T.search_term)),
            func.sum(T.impressions),
            func.sum(T.clicks),
            func.sum(T.orders_7d),
            func.sum(T.spend),
            func.sum(T.sales_7d),
            func.max(T.campaign_name),
        )
        .where(T.store_code.in_(store_codes), T.currency == currency, T.report_date > since)
        .group_by(T.store_code, func.lower(func.trim(T.search_term)))
    ).all()
    out: dict[str, dict[str, TermStat]] = {}
    for store, term, impr, clicks, orders, spend, sales, campaign in rows:
        if not term or term.startswith("b0") and len(term) == 10:
            continue  # ASIN 定向不是搜索词
        out.setdefault(term, {})[store] = TermStat(store, term, int(impr or 0), int(clicks or 0), int(orders or 0), Decimal(spend or 0), Decimal(sales or 0), campaign or "")
    return out


def _same_line(mine: TermStat, other: TermStat) -> bool:
    return mine.line == other.line and mine.line != "other"


def rule_listing_cvr_gap(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    """笑笑:同词同货,兄弟店每百次点击的单数是我们的两倍以上 → 页面接不住这个词。"""
    siblings = sibling_stores(db, store_code, currency)
    if not siblings:
        return []
    since = as_of - timedelta(days=WINDOW_DAYS)
    stats = term_stats(db, store_codes=[store_code, *siblings], currency=currency, since=since)
    candidates: list[tuple[TermStat, TermStat]] = []
    for term, by_store in stats.items():
        mine = by_store.get(store_code)
        if mine is None or mine.clicks < CVR_MIN_CLICKS:
            continue
        rivals = [s for code, s in by_store.items() if code != store_code and s.clicks >= CVR_MIN_CLICKS and s.orders >= CVR_BEST_MIN_ORDERS and _same_line(mine, s)]
        if not rivals:
            continue
        best = max(rivals, key=lambda s: s.cvr)
        if best.cvr > 0 and mine.cvr < best.cvr * CVR_GAP_RATIO:
            candidates.append((mine, best))
    candidates.sort(key=lambda pair: -pair[0].clicks)
    drafts: list[SuggestionDraft] = []
    for mine, best in candidates[:CVR_LIMIT]:
        label = PRODUCT_LINE_LABELS.get(mine.line, mine.line)
        drafts.append(
            SuggestionDraft(
                employee=EMPLOYEE_A,
                store_code=store_code,
                action_type=ACTION_LISTING_CVR_GAP,
                severity="warn" if mine.clicks >= CVR_WARN_CLICKS else "info",
                title=f"「{mine.term}」同一款{label},{best.store_code} 每百次点击 {best.cvr:.1f} 单,我们 {mine.cvr:.1f} 单——页面接不住这个词",
                why=(
                    f"近 {WINDOW_DAYS} 天这个词在 {store_code} 点了 {mine.clicks} 次成交 {mine.orders} 单,"
                    f"在 {best.store_code} 点了 {best.clicks} 次成交 {best.orders} 单。同一批货、同一个词,差的是标题 / 五点 / 价格 / 评论,不是货。"
                ),
                prediction=f"把 {best.store_code} 在这个词上的标题和五点差异对照出来改稿;改后 14 天看每百次点击的单数是否向 {best.cvr:.1f} 靠拢。",
                subject=f"{mine.line}|{mine.term}",
                evidence={
                    "term": mine.term,
                    "product_line": mine.line,
                    "mine": {"store": store_code, "clicks": mine.clicks, "orders": mine.orders, "cvr_pct": round(mine.cvr, 1), "campaign": mine.campaign},
                    "best": {"store": best.store_code, "clicks": best.clicks, "orders": best.orders, "cvr_pct": round(best.cvr, 1), "campaign": best.campaign},
                    "window_days": WINDOW_DAYS,
                },
            )
        )
    return drafts


def rule_screen_ctr_gap(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    """熊:同词曝光够,兄弟店点击率是我们的两倍以上 → 搜索页同屏输了(主图 / 标题前 80 字符)。"""
    siblings = sibling_stores(db, store_code, currency)
    if not siblings:
        return []
    since = as_of - timedelta(days=WINDOW_DAYS)
    stats = term_stats(db, store_codes=[store_code, *siblings], currency=currency, since=since)
    candidates: list[tuple[TermStat, TermStat]] = []
    for term, by_store in stats.items():
        mine = by_store.get(store_code)
        if mine is None or mine.impressions < CTR_MIN_IMPRESSIONS:
            continue
        rivals = [s for code, s in by_store.items() if code != store_code and s.impressions >= CTR_MIN_IMPRESSIONS and s.clicks >= CTR_BEST_MIN_CLICKS and _same_line(mine, s)]
        if not rivals:
            continue
        best = max(rivals, key=lambda s: s.ctr)
        if best.ctr > 0 and mine.ctr < best.ctr * CTR_GAP_RATIO:
            candidates.append((mine, best))
    candidates.sort(key=lambda pair: -pair[0].impressions)
    drafts: list[SuggestionDraft] = []
    for mine, best in candidates[:CTR_LIMIT]:
        label = PRODUCT_LINE_LABELS.get(mine.line, mine.line)
        drafts.append(
            SuggestionDraft(
                employee=EMPLOYEE_B,
                store_code=store_code,
                action_type=ACTION_SCREEN_CTR_GAP,
                severity="warn" if mine.impressions >= CTR_MIN_IMPRESSIONS * 4 else "info",
                title=f"「{mine.term}」搜索页同屏:{best.store_code} 点击率 {best.ctr:.2f}%,我们 {mine.ctr:.2f}%——主图在这个词上输了",
                why=(
                    f"近 {WINDOW_DAYS} 天这个词在 {store_code} 曝光 {mine.impressions} 次点 {mine.clicks} 次,"
                    f"在 {best.store_code} 曝光 {best.impressions} 次点 {best.clicks} 次。同一款{label}、同一个词,买家在搜索页只看主图和标题前半句。"
                ),
                prediction=f"把两家店在这个词上的搜索结果截图同屏对照,给主图写一份带证据的 brief;换图后 14 天看点击率是否向 {best.ctr:.2f}% 靠拢。",
                subject=f"{mine.line}|{mine.term}",
                evidence={
                    "term": mine.term,
                    "product_line": mine.line,
                    "mine": {"store": store_code, "impressions": mine.impressions, "clicks": mine.clicks, "ctr_pct": round(mine.ctr, 2), "campaign": mine.campaign},
                    "best": {"store": best.store_code, "impressions": best.impressions, "clicks": best.clicks, "ctr_pct": round(best.ctr, 2), "campaign": best.campaign},
                    "window_days": WINDOW_DAYS,
                },
            )
        )
    return drafts


CROSS_RULES = (rule_listing_cvr_gap, rule_screen_ctr_gap)

__all__ = ["ACTION_LISTING_CVR_GAP", "ACTION_SCREEN_CTR_GAP", "CROSS_RULES", "TermStat", "rule_listing_cvr_gap", "rule_screen_ctr_gap", "term_stats"]
