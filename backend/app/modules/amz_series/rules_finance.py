"""殷乐乐(E,财务)的规则。口径在 finance.py / skills/e/finance-pnl.md。

窗口按这家店「交易数据的最后一天」算(不是广告数据的最后一天):
- missing_cost(bad):近 30 天有销量但没填成本的 SKU——账算不了,这是「卡住」,一店一条;
- line_loss(bad):某产品线近 14 天扣完广告的利润 < 0(取代殷素素原来的 loss_line)。
  **只有广告报表完整覆盖这 14 天、而且这条线的成本都填了**才下结论;否则不说话(不拿残缺的数吓人);
- margin_floor(warn):某 SKU 近 14 天单件毛利(扣广告前)< 底线;
- refund_spike(warn):某 SKU 近 14 天退款率 > 前 28 天的 2 倍,且至少 3 单退款;
- fee_change(info):某 SKU 单件 FBA 费比前 30 天变动 > 10%(亚马逊调费 / 重新量尺寸)。
不 commit。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from . import finance
from .constants import EMPLOYEE_E
from .rules import SuggestionDraft

WINDOW_DAYS = 14
BASELINE_DAYS = 28
FEE_BASELINE_DAYS = 30
MISSING_COST_LOOKBACK = 30
MARGIN_FLOOR_USD = Decimal("4")
MARGIN_MIN_UNITS = 5
REFUND_MIN_ORDERS = 3
REFUND_RATIO = 2.0
FEE_CHANGE_PCT = 10.0
FEE_MIN_UNITS = 5
LINE_LOSS_MIN_SPEND = Decimal("50")


def _money(value: Decimal | float) -> str:
    return f"${float(value):,.2f}"


def rule_missing_cost(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    until = finance.data_until(db, store_code)
    if until is None:
        return []
    book = finance.ledger(db, store_code, since=until - timedelta(days=MISSING_COST_LOOKBACK - 1), until=until)
    missing = sorted(((sku, sb.missing_cost_units) for sku, sb in book["skus"].items() if sb.missing_cost_units > 0), key=lambda x: -x[1])
    if not missing:
        return []
    units = sum(n for _s, n in missing)
    listing = "、".join(f"{sku}({n} 件)" for sku, n in missing[:8]) + (" 等" if len(missing) > 8 else "")
    return [
        SuggestionDraft(
            employee=EMPLOYEE_E,
            store_code=store_code,
            action_type="missing_cost",
            severity="bad",
            title=f"{store_code} 有 {len(missing)} 个 SKU 没填成本,账算不完整(近 30 天 {units} 件)",
            why=f"没有出厂价和头程,这些件的利润我没法算:{listing}。我不会猜成本,填上之前这家店每天的利润都标「不完整」。",
            prediction="在「财务」页的成本表里填出厂价、头程(元 / 件)和生效日期;填完下一轮就重算,之前的日子也会按生效日期补上。",
            subject="missing_cost",
            evidence={"skus": [s for s, _n in missing], "units": units, "until": until.isoformat()},
        )
    ]


def _window(db: Session, store_code: str) -> tuple[date, dict, dict] | None:
    until = finance.data_until(db, store_code)
    if until is None:
        return None
    recent = finance.ledger(db, store_code, since=until - timedelta(days=WINDOW_DAYS - 1), until=until)
    prior = finance.ledger(db, store_code, since=until - timedelta(days=WINDOW_DAYS + BASELINE_DAYS - 1), until=until - timedelta(days=WINDOW_DAYS))
    return until, recent, prior


def rule_line_loss(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    win = _window(db, store_code)
    if win is None:
        return []
    until, recent, _prior = win
    if recent["last_ads"] is None or recent["last_ads"] < until:
        return []  # 广告费没覆盖满这 14 天,扣完广告的利润算不准,不下结论
    drafts = []
    for line in finance.line_table(db, store_code, recent):
        profit = line["profit_after_ads"]
        if profit is None or profit >= 0 or Decimal(str(line["ad_spend"])) < LINE_LOSS_MIN_SPEND:
            continue
        label = line["label"]
        drafts.append(
            SuggestionDraft(
                employee=EMPLOYEE_E,
                store_code=store_code,
                action_type="line_loss",
                severity="bad",
                title=f"{label}:近 14 天扣完广告亏 {_money(-profit)}(广告花 {_money(line['ad_spend'])})",
                why=f"这条线近 14 天卖了 {line['units']} 件、销售额 {_money(line['sales'])},扣广告前毛利 {_money(line['gross_before_ads'])}(毛利率 {line['margin_pct']}%),广告一扣就成了负数。广告自己的账:{_money(line['ad_pnl'] or 0)}。",
                prediction="这是要不要继续投的决定,交给殷素素出方案:A 降到保排名的最低预算 · B 停广告两周看自然单接不接得住 · C 保持并写明理由(进经验库)。",
                subject=f"line_loss|{line['product_line']}",
                evidence={"product_line": line["product_line"], "window_days": WINDOW_DAYS, "until": until.isoformat(), **{k: line[k] for k in ("units", "sales", "gross_before_ads", "ad_spend", "profit_after_ads", "margin_pct", "ad_pnl")}, "handoff": ["D"]},
            )
        )
    return drafts


def _per_unit(value: Decimal, units: int) -> Decimal:
    return value / units if units else Decimal(0)


def rule_sku_health(db: Session, store_code: str, currency: str, as_of: date) -> list[SuggestionDraft]:
    """单件毛利底线 / 退款突增 / FBA 费变动,一次算完(共用同一份账)。"""
    win = _window(db, store_code)
    if win is None:
        return []
    until, recent, prior = win
    fee_base = finance.ledger(db, store_code, since=until - timedelta(days=WINDOW_DAYS + FEE_BASELINE_DAYS - 1), until=until - timedelta(days=WINDOW_DAYS))
    drafts: list[SuggestionDraft] = []
    for sku, sb in recent["skus"].items():
        if sku.startswith("("):
            continue
        # 1. 单件毛利底线(扣广告前,成本齐了才算)
        if sb.units >= MARGIN_MIN_UNITS and sb.missing_cost_units == 0:
            unit_margin = _per_unit(sb.sales + sb.fees + sb.refunds - sb.cogs, sb.units)
            if unit_margin < MARGIN_FLOOR_USD:
                drafts.append(
                    SuggestionDraft(
                        employee=EMPLOYEE_E,
                        store_code=store_code,
                        action_type="margin_floor",
                        severity="warn",
                        title=f"{sku} 单件毛利 {_money(unit_margin)},低于底线 {_money(MARGIN_FLOOR_USD)}(还没扣广告)",
                        why=f"近 14 天 {sb.units} 件:单件售价 {_money(_per_unit(sb.sales, sb.units))}、亚马逊费用 {_money(_per_unit(-sb.fees, sb.units))}、成本 {_money(_per_unit(sb.cogs, sb.units))}、退款摊到每件 {_money(_per_unit(-sb.refunds, sb.units))}。再扣广告基本就不赚了。",
                        prediction="看三个旋钮:价格(和对手比还有没有空间)、广告(这件货的广告是不是在亏钱买量,问殷素素)、成本(头程能不能降)。",
                        subject=f"margin_floor|{sku}",
                        evidence={"sku": sku, "units": sb.units, "unit_margin": float(round(unit_margin, 2)), "floor": float(MARGIN_FLOOR_USD), "until": until.isoformat()},
                    )
                )
        # 2. 退款突增
        pb = prior["skus"].get(sku)
        if sb.refund_orders >= REFUND_MIN_ORDERS and sb.units:
            rate = sb.refund_orders / sb.units
            base = (pb.refund_orders / pb.units) if pb and pb.units else 0.0
            if base == 0.0 or rate > base * REFUND_RATIO:
                drafts.append(
                    SuggestionDraft(
                        employee=EMPLOYEE_E,
                        store_code=store_code,
                        action_type="refund_spike",
                        severity="warn",
                        title=f"{sku} 退款变多:近 14 天 {sb.refund_orders} 单 / {sb.units} 件({rate * 100:.0f}%),之前 {base * 100:.0f}%",
                        why="退款一多,钱和排名一起掉。常见原因:一批货质量问题、页面没讲清楚(预期落差)、物流破损。",
                        prediction="把这段时间的差评贴进竞品页的评论框,看是哪一簇在涨;是页面的问题交给殷笑笑,是货的问题要找工厂。",
                        subject=f"refund_spike|{sku}",
                        evidence={"sku": sku, "refund_orders": sb.refund_orders, "units": sb.units, "rate_pct": round(rate * 100, 1), "base_pct": round(base * 100, 1), "until": until.isoformat()},
                    )
                )
        # 3. FBA 费变动
        fb = fee_base["skus"].get(sku)
        if fb and fb.units >= FEE_MIN_UNITS and sb.units >= 3 and fb.fba_fees and sb.fba_fees:
            now_fee, base_fee = _per_unit(-sb.fba_fees, sb.units), _per_unit(-fb.fba_fees, fb.units)
            if base_fee > 0:
                change = float((now_fee - base_fee) / base_fee * 100)
                if abs(change) > FEE_CHANGE_PCT:
                    drafts.append(
                        SuggestionDraft(
                            employee=EMPLOYEE_E,
                            store_code=store_code,
                            action_type="fee_change",
                            severity="info",
                            title=f"{sku} 单件 FBA 费 {_money(base_fee)} → {_money(now_fee)}({change:+.0f}%)",
                            why="可能是亚马逊调了费率,也可能是仓库重新量了尺寸 / 重量,把货归到了更贵的档。",
                            prediction="涨了的话去后台查这个 SKU 的尺寸重量有没有被改;量错了可以申请重新测量。",
                            subject=f"fee_change|{sku}|{until.isoformat()[:7]}",
                            evidence={"sku": sku, "fee_now": float(round(now_fee, 2)), "fee_before": float(round(base_fee, 2)), "change_pct": round(change, 1), "until": until.isoformat()},
                        )
                    )
    return drafts


FINANCE_RULES = (rule_missing_cost, rule_line_loss, rule_sku_health)

__all__ = ["FINANCE_RULES", "MARGIN_FLOOR_USD", "rule_line_loss", "rule_missing_cost", "rule_sku_health"]
