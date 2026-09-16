"""喂给员工的只读快照:这名员工、这位说话人能看的店铺范围内,有什么、截至哪天。

死规矩(agent-field-name-ambiguity):字段名先消歧、计数先算好再喂;模型不该自己数。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....models.user import User
from ..deps import granted_store_codes
from ..models import AmzStore
from ..persona import persona_for
from ..rules import store_as_of
from ..suggestions import list_suggestions, suggestion_view
from .. import products, work_log

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
        "我的工作日志(硬记忆,来自数据库)": work_log_section(db, employee=employee, store_codes=store_codes, question=question),
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
