"""员工消息(建议)的读写:列表、决定(影子期只记录)、员工面板汇总、总览曲线。不 commit。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from ...models.user import User
from ...repositories.operation_logs import create_operation_log
from . import work_log
from .constants import EMPLOYEE_ROLE_LABELS, EMPLOYEE_USERNAMES, EMPLOYEES
from .persona import persona_for
from .models import AmzAdSearchTerm, AmzSalesDaily, AmzSuggestion, AmzTransaction
from .service import AmzServiceError

DECISIONS = ("approve", "reject", "later")
DECISION_STATUS = {"approve": "approved", "reject": "rejected", "later": "later"}
SEVERITY_RANK = {"bad": 0, "warn": 1, "info": 2, "good": 3}


def suggestion_view(row: AmzSuggestion) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "employee": row.employee,
        "employee_label": EMPLOYEE_ROLE_LABELS.get(row.employee, row.employee),
        "employee_name": persona_for(row.employee).name if row.employee in EMPLOYEES else row.employee,
        "store_code": row.store_code,
        "action_type": row.action_type,
        "severity": row.severity,
        "title": row.title,
        "why": row.why,
        "prediction": row.prediction,
        "evidence": row.evidence_json or {},
        "level": row.level,
        "status": row.status,
        "reject_reason": row.reject_reason,
        "decided_by_user_id": row.decided_by_user_id,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "as_of": row.as_of.isoformat() if row.as_of else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_suggestions(
    db: Session,
    *,
    store_codes: list[str] | None,
    employee: str | None = None,
    status: str | None = "open",
    limit: int = 200,
) -> list[AmzSuggestion]:
    query = select(AmzSuggestion)
    if store_codes is not None:
        if not store_codes:
            return []
        query = query.where(AmzSuggestion.store_code.in_(store_codes))
    if employee:
        query = query.where(AmzSuggestion.employee == employee.upper())
    if status and status != "all":
        query = query.where(AmzSuggestion.status == status)
    rows = list(db.scalars(query.order_by(AmzSuggestion.updated_at.desc()).limit(limit)))
    rows.sort(key=lambda r: (SEVERITY_RANK.get(r.severity, 9), -(r.updated_at.timestamp() if r.updated_at else 0)))
    return rows


def decide_suggestion(
    db: Session,
    *,
    suggestion_id: UUID,
    decision: str,
    reason: str | None,
    actor: User,
    allowed_store_codes: list[str] | None,
    request_id: str | None = None,
) -> AmzSuggestion:
    if decision not in DECISIONS:
        raise AmzServiceError(f"unknown decision: {decision}", status_code=422, code="amz_decision_invalid")
    row = db.get(AmzSuggestion, suggestion_id)
    if row is None:
        raise AmzServiceError("suggestion not found", status_code=404, code="amz_suggestion_not_found")
    if allowed_store_codes is not None and row.store_code not in allowed_store_codes:
        raise AmzServiceError("no access to this store", status_code=403, code="amz_store_forbidden")
    if decision == "reject" and not (reason or "").strip():
        # 驳回必须写原因:那一句话是经验库的训练信号。
        raise AmzServiceError("驳回要写一句原因", status_code=422, code="amz_reject_reason_required")
    row.status = DECISION_STATUS[decision]
    row.reject_reason = (reason or "").strip() or None
    row.decided_by_user_id = int(actor.id)
    row.decided_at = datetime.now(UTC)
    db.add(row)
    db.flush()
    # 硬记忆:谁、什么时候、为什么放行 / 驳回 / 稍后——员工聊天时随时能读到。
    work_log.record_decision(db, row=row, decision=decision, actor_user_id=int(actor.id))
    create_operation_log(
        db,
        actor_type="user",
        actor_id=str(actor.id),
        action=f"amz.suggestion.{decision}",
        target_type="amz_suggestion",
        target_id=str(row.id),
        result="success",
        request_id=request_id,
        details={
            "store_code": row.store_code,
            "employee": row.employee,
            "action_type": row.action_type,
            "level": row.level,
            "reason": row.reject_reason,
            # 影子期:决定只记录,不触发任何对亚马逊的写。
            "shadow": row.level == "L0",
        },
    )
    return row


def employee_panel(db: Session, *, store_codes: list[str] | None) -> dict[str, Any]:
    """员工面板:每人未读(open)数、最高严重度、最新一条消息。"""
    rows = list_suggestions(db, store_codes=store_codes, status="open", limit=500)
    by_employee: dict[str, list[AmzSuggestion]] = {e: [] for e in EMPLOYEES}
    for row in rows:
        by_employee.setdefault(row.employee, []).append(row)
    items = []
    urgent_total = 0
    for employee in EMPLOYEES:
        mine = by_employee.get(employee, [])
        urgent = [r for r in mine if r.severity == "bad"]
        urgent_total += len(urgent)
        latest = mine[0] if mine else None
        persona = persona_for(employee)
        items.append(
            {
                "employee": employee,
                "username": EMPLOYEE_USERNAMES[employee],
                "role_label": EMPLOYEE_ROLE_LABELS[employee],
                "name": persona.name,
                "gender": persona.gender,
                "character": persona.character,
                "open": len(mine),
                "urgent": len(urgent),
                "latest": suggestion_view(latest) if latest else None,
            }
        )
    return {"items": items, "open_total": len(rows), "urgent_total": urgent_total}


def daily_series(db: Session, *, store_codes: list[str] | None, days: int = 30) -> dict[str, Any]:
    """总览两条线(日粒度,种子期用;API 接上后换小时):广告花费 / 广告销售 / 总销售额(交易一览 Order 行) / TACOS。"""
    if store_codes is not None and not store_codes:
        return {"days": [], "as_of": None}
    T = AmzAdSearchTerm
    ads_q = select(T.report_date, func.sum(T.spend), func.sum(T.sales_7d), func.sum(T.orders_7d))
    if store_codes is not None:
        ads_q = ads_q.where(T.store_code.in_(store_codes))
    as_of = db.scalar(select(func.max(T.report_date)).where(T.store_code.in_(store_codes)) if store_codes is not None else select(func.max(T.report_date)))
    if as_of is None:
        return {"days": [], "as_of": None}
    since = as_of - timedelta(days=days)
    ads = {
        row[0]: {"spend": Decimal(row[1] or 0), "ad_sales": Decimal(row[2] or 0), "ad_orders": int(row[3] or 0)}
        for row in db.execute(ads_q.where(T.report_date > since, T.report_date <= as_of).group_by(T.report_date)).all()
    }
    # 总销售额:每个 (店, 天) 优先用 SP-API 的销售与流量报表(店铺合计行),没有的天回落到交易一览。
    X = AmzTransaction
    day_col = cast(X.posted_at, Date)
    tx_q = select(X.store_code, day_col, func.sum(X.product_sales * X.fx_rate), func.count(func.distinct(X.order_id))).where(
        X.txn_type.in_(("Order", "Bestellung")), day_col > since, day_col <= as_of
    )
    if store_codes is not None:
        tx_q = tx_q.where(X.store_code.in_(store_codes))
    per_store_day: dict[tuple[str, date], dict[str, Any]] = {
        (row[0], row[1]): {"sales": Decimal(row[2] or 0), "orders": int(row[3] or 0), "sessions": 0, "source": "transactions"}
        for row in db.execute(tx_q.group_by(X.store_code, day_col)).all()
    }
    S = AmzSalesDaily
    api_q = select(S.store_code, S.report_date, S.ordered_product_sales, S.total_order_items, S.sessions, S.currency).where(
        S.child_asin == "", S.report_date > since, S.report_date <= as_of
    )
    if store_codes is not None:
        api_q = api_q.where(S.store_code.in_(store_codes))
    for store_code, day, amount, orders, sessions, currency in db.execute(api_q).all():
        usd = Decimal(amount or 0) * (Decimal("1.08") if currency == "EUR" else Decimal(1))
        per_store_day[(store_code, day)] = {"sales": usd, "orders": int(orders or 0), "sessions": int(sessions or 0), "source": "api"}
    sales: dict[date, dict[str, Any]] = {}
    for (_, day), item in per_store_day.items():
        bucket = sales.setdefault(day, {"sales": Decimal(0), "orders": 0, "sessions": 0, "sources": set()})
        bucket["sales"] += item["sales"]
        bucket["orders"] += item["orders"]
        bucket["sessions"] += item["sessions"]
        bucket["sources"].add(item["source"])
    out = []
    cursor = since + timedelta(days=1)
    while cursor <= as_of:
        a = ads.get(cursor, {"spend": Decimal(0), "ad_sales": Decimal(0), "ad_orders": 0})
        s = sales.get(cursor, {"sales": Decimal(0), "orders": 0, "sessions": 0, "sources": set()})
        tacos = float(a["spend"] / s["sales"] * 100) if s["sales"] else None
        sources = s["sources"]
        out.append(
            {
                "date": cursor.isoformat(),
                "spend_usd": round(float(a["spend"]), 2),
                "ad_sales_usd": round(float(a["ad_sales"]), 2),
                "ad_orders": a["ad_orders"],
                "sales_usd": round(float(s["sales"]), 2),
                "orders": s["orders"],
                "sessions": s["sessions"],
                "sales_source": "mixed" if len(sources) > 1 else (next(iter(sources)) if sources else "none"),
                "tacos_pct": round(tacos, 1) if tacos is not None else None,
            }
        )
        cursor += timedelta(days=1)
    return {"days": out, "as_of": as_of.isoformat(), "note": "日粒度;总销售额优先用 SP-API 销售与流量报表,没接 API 的店回落到交易一览;广告花费按报表原币(德国欧元未折)"}


__all__ = ["DECISIONS", "daily_series", "decide_suggestion", "employee_panel", "list_suggestions", "suggestion_view"]
