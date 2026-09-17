"""喂给员工的只读快照:这名员工、这位说话人能看的店铺范围内,有什么、截至哪天。

死规矩(agent-field-name-ambiguity):字段名先消歧、计数先算好再喂;模型不该自己数。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....models.user import User
from ..deps import granted_store_codes
from datetime import date, timedelta

from ..models import AmzSalesDaily, AmzSqp, AmzStore
from ..persona import persona_for
from ..rules import store_as_of
from ..suggestions import list_suggestions, suggestion_view
from .. import experience, products, work_log

MAX_OPEN_IN_SNAPSHOT = 8
MAX_RECENT_LOG = 12
MAX_RELEVANT_LOG = 30


def speaker_store_codes(db: Session, speaker: User | None) -> list[str] | None:
    """说话人能看的店铺:owner → None(全部);有授权 → 那些店;没授权 → []。"""
    if speaker is None:
        return []
    return granted_store_codes(db, speaker)


def compact_suggestion(view: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": view["id"],
        "店铺": view["store_code"],
        "事情": view["title"],
        "为什么": view["why"],
        "预计": view["prediction"],
        "严重度": view["severity"],
        "状态": view["status"],
        "数据截至": view["as_of"],
    }


def employee_snapshot(db: Session, *, employee: str, store_codes: list[str] | None, question: str = "") -> dict[str, Any]:
    persona = persona_for(employee)
    stores = list(db.scalars(select(AmzStore).order_by(AmzStore.store_code)))
    if store_codes is not None:
        stores = [s for s in stores if s.store_code in set(store_codes)]
    open_rows = list_suggestions(db, store_codes=store_codes, employee=employee, status="open", limit=200)
    open_views = [suggestion_view(r) for r in open_rows]
    urgent = [v for v in open_views if v["severity"] == "bad"]
    return {
        "我是": {"名字": persona.name, "岗位": persona.role},
        "阶段": "影子期(只建议,不动亚马逊)",
        "店铺": [
            {
                "店铺": s.store_code,
                "名称": s.display_name,
                "公司": s.company_name,
                "币种": s.currency,
                "数据截至": (store_as_of(db, s.store_code) or "").__str__() or "还没有数据",
            }
            for s in stores
        ],
        "我们在卖的产品(名册,来自交易数据)": products.roster(db, store_codes=store_codes) or "还没有名册",
        "我名下待看的建议": {
            "总数": len(open_views),
            "紧急数": len(urgent),
            "最要紧的几条": [compact_suggestion(v) for v in open_views[:MAX_OPEN_IN_SNAPSHOT]],
            "说明": "严重度 bad=要人拍板;warn=看一眼;info=知道就好。放行/驳回在控制台浮窗里点,不在聊天里。",
        },
        "最近 7 天销售与流量(SP-API,按子 ASIN)": sales_section(db, store_codes=store_codes),
        "上一整周搜索词表现 SQP(全市场 vs 我们)": sqp_section(db, store_codes=store_codes),
        "经验库(跟我有关的;回头看建议对不对、老板驳回的规律、参数漂移)": [experience.view(r)["statement"] for r in experience.list_entries(db, store_codes=store_codes, employee=employee, limit=8)] or "还没有经验条目",
        "我的工作日志(硬记忆,来自数据库)": work_log_section(db, employee=employee, store_codes=store_codes, question=question),
    }


def sales_section(db: Session, *, store_codes: list[str] | None, days: int = 7, limit: int = 10) -> Any:
    """每个 (店, 子 ASIN) 最近 N 天的件数 / 访问 / 转化率;店铺合计行另列。没接 API 的店就没有。"""
    if store_codes is not None and not store_codes:
        return "没有店铺"
    latest = db.scalar(select(func.max(AmzSalesDaily.report_date)).where(AmzSalesDaily.store_code.in_(store_codes)) if store_codes is not None else select(func.max(AmzSalesDaily.report_date)))
    if latest is None:
        return "还没有 SP-API 数据(该店未接入或未回填)"
    since = latest - timedelta(days=days - 1)
    S = AmzSalesDaily
    q = (
        select(S.store_code, S.child_asin, S.parent_asin, func.sum(S.units_ordered), func.sum(S.sessions), func.sum(S.ordered_product_sales), func.max(S.currency))
        .where(S.report_date >= since, S.report_date <= latest)
        .group_by(S.store_code, S.child_asin, S.parent_asin)
    )
    if store_codes is not None:
        q = q.where(S.store_code.in_(store_codes))
    rows = db.execute(q).all()
    totals = [r for r in rows if r[1] == ""]
    asins = sorted([r for r in rows if r[1] != ""], key=lambda r: -int(r[3] or 0))[:limit]

    def _cvr(units: int, sessions: int) -> float | None:
        return round(units / sessions * 100, 2) if sessions else None

    return {
        "数据区间": f"{since.isoformat()} 至 {latest.isoformat()}",
        "店铺合计": [{"店铺": r[0], "件数": int(r[3] or 0), "访问": int(r[4] or 0), "销售额": f"{float(r[5] or 0):.2f} {r[6]}", "转化率%": _cvr(int(r[3] or 0), int(r[4] or 0))} for r in totals],
        "按子ASIN(前几名)": [{"店铺": r[0], "ASIN": r[1], "父ASIN": r[2], "件数": int(r[3] or 0), "访问": int(r[4] or 0), "转化率%": _cvr(int(r[3] or 0), int(r[4] or 0))} for r in asins],
        "说明": "转化率 = 件数 / 访问;这是自然+广告合计的真实盘子,不是广告报表。",
    }


def sqp_section(db: Session, *, store_codes: list[str] | None, limit: int = 10) -> Any:
    if store_codes is not None and not store_codes:
        return "没有店铺"
    latest = db.scalar(select(func.max(AmzSqp.period_start)).where(AmzSqp.store_code.in_(store_codes)) if store_codes is not None else select(func.max(AmzSqp.period_start)))
    if latest is None:
        return "还没有 SQP 数据"
    q = select(AmzSqp).where(AmzSqp.period_start == latest)
    if store_codes is not None:
        q = q.where(AmzSqp.store_code.in_(store_codes))
    # 先按我们拿到的点击排(跟我们有关的词),再按全市场曝光——否则 "camping" 这种大词永远占满,而我们份额是 0。
    rows = sorted(db.scalars(q), key=lambda r: (-(r.clicks_asin or 0), -(r.impressions_total or 0)))[:limit]
    return {
        "周": f"{latest.isoformat()} 起的一周",
        "按我们拿到的点击排前几名": [
            {
                "店铺": r.store_code,
                "ASIN": r.asin,
                "搜索词": r.search_query,
                "全市场曝光": r.impressions_total,
                "我们曝光份额%": float(r.impressions_share_pct) if r.impressions_share_pct is not None else None,
                "我们点击份额%": float(r.clicks_share_pct) if r.clicks_share_pct is not None else None,
                "我们购买份额%": float(r.purchases_share_pct) if r.purchases_share_pct is not None else None,
            }
            for r in rows
        ],
        "判据": "点击份额 > 购买份额 = 详情页在漏(人点进来了没买);曝光份额低 = 词没接住(标题/后台词)。",
    }


def work_log_section(db: Session, *, employee: str, store_codes: list[str] | None, question: str) -> dict[str, Any]:
    """先给「跟这句话有关的」,再给「最近的」;两者都带日期、店铺、对象、为什么。库里没有就明说没有。"""
    related = work_log.relevant(db, employee=employee, store_codes=store_codes, question=question, limit=MAX_RELEVANT_LOG) if question.strip() else []
    related_ids = {r.id for r in related}
    latest = [r for r in work_log.recent(db, employee=employee, store_codes=store_codes, limit=MAX_RECENT_LOG) if r.id not in related_ids]
    tallies = work_log.counts(db, employee=employee, store_codes=store_codes)
    return {
        "总条数": sum(tallies.values()),
        "按类型": {work_log.KIND_LABELS.get(k, k): v for k, v in tallies.items()},
        "跟这句话有关的": [work_log.view(r) for r in related] or "没有相关记录",
        "最近的": [work_log.view(r) for r in latest] or "还没有记录",
        "说明": "这些是数据库里的记录,不是你的印象。问到某店某 ASIN 最近做了什么、为什么,照这里答并带日期;这里没有就说没有记录。",
    }


__all__ = ["compact_suggestion", "employee_snapshot", "speaker_store_codes"]
