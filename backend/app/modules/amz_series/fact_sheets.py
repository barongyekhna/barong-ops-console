"""产品事实表的读写:按 (产品线, 店, SKU) 一份;保存即代码判「够不够」,点「判一下」再叫模型。不 commit。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models.user import User
from . import sufficiency, work_log
from .catalog import AGENT_HOME_COMPANY, store_spec
from .constants import EMPLOYEE_A
from .models import AmzFactSheet
from .rules import PRODUCT_LINE_LABELS
from .service import AmzServiceError

PRODUCT_LINES: tuple[str, ...] = ("pump", "heater", "flash", "nail", "bundle", "other")
FACT_FIELDS: tuple[str, ...] = ("is", "how_it_works", "is_not", "specs", "indicators", "package", "audience", "misreadings", "cost", "competitor_asins", "notes")


def scope_key(product_line: str, store_code: str | None, sku: str | None) -> str:
    return f"{product_line}|{(store_code or '').lower()}|{(sku or '').strip()}"


def normalize_facts(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    facts: dict[str, Any] = {}
    for field in ("is", "how_it_works", "is_not", "indicators", "package", "audience", "misreadings", "notes"):
        facts[field] = str(raw.get(field) or "").strip()
    specs = raw.get("specs")
    if isinstance(specs, dict):
        facts["specs"] = {str(k).strip(): str(v).strip() for k, v in specs.items() if str(k).strip() and str(v or "").strip()}
    else:
        facts["specs"] = {}
    cost = raw.get("cost") if isinstance(raw.get("cost"), dict) else {}
    facts["cost"] = {}
    for key in ("factory_cny", "freight_cny", "price_usd"):
        value = cost.get(key)
        try:
            number = float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            number = None
        if number is not None and number >= 0:
            facts["cost"][key] = number
    asins = raw.get("competitor_asins") or []
    if isinstance(asins, str):
        asins = [part for part in asins.replace(",", " ").replace("\n", " ").split() if part]
    facts["competitor_asins"] = sorted({str(a).strip().upper() for a in asins if str(a).strip()})
    return facts


def view(row: AmzFactSheet) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "product_line": row.product_line,
        "product_line_label": PRODUCT_LINE_LABELS.get(row.product_line, row.product_line),
        "store_code": row.store_code,
        "sku": row.sku,
        "title": row.title,
        "facts": row.facts_json or {},
        "sufficiency": row.sufficiency_json or {},
        "version": row.version,
        "status": row.status,
        "updated_by_user_id": row.updated_by_user_id,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_sheets(db: Session, *, store_codes: list[str] | None, product_line: str | None = None) -> list[AmzFactSheet]:
    query = select(AmzFactSheet)
    if product_line:
        query = query.where(AmzFactSheet.product_line == product_line)
    rows = list(db.scalars(query.order_by(AmzFactSheet.product_line, AmzFactSheet.store_code.nulls_first(), AmzFactSheet.sku.nulls_first())))
    if store_codes is not None:
        rows = [r for r in rows if r.store_code is None or r.store_code in store_codes]
    return rows


def _org_for(store_code: str | None) -> str:
    spec = store_spec(store_code or "")
    return spec.company.org_id if spec is not None else AGENT_HOME_COMPANY.org_id


def upsert_sheet(
    db: Session,
    *,
    product_line: str,
    store_code: str | None,
    sku: str | None,
    title: str,
    facts: dict[str, Any] | None,
    actor: User,
) -> AmzFactSheet:
    product_line = (product_line or "").strip().lower()
    if product_line not in PRODUCT_LINES:
        raise AmzServiceError(f"unknown product line: {product_line}", status_code=422, code="amz_product_line_invalid")
    store_code = (store_code or "").strip().lower() or None
    if store_code and store_spec(store_code) is None:
        raise AmzServiceError(f"unknown store: {store_code}", status_code=422, code="amz_store_invalid")
    title = (title or "").strip()[:255]
    if not title:
        raise AmzServiceError("事实表要有个名字", status_code=422, code="amz_title_required")
    clean = normalize_facts(facts)
    key = scope_key(product_line, store_code, sku)
    row = db.scalar(select(AmzFactSheet).where(AmzFactSheet.scope_key == key))
    created = row is None
    if row is None:
        row = AmzFactSheet(scope_key=key, product_line=product_line, store_code=store_code, sku=(sku or "").strip() or None, title=title, facts_json=clean, version=1)
    else:
        row.title = title
        row.facts_json = clean
        row.version = int(row.version or 0) + 1
    # 保存即判(代码层,不出网);模型核对另点。
    row.sufficiency_json = sufficiency.judge(clean, product_line=product_line, title=title, org_id=_org_for(store_code), with_model=False)
    row.status = "ready" if all(row.sufficiency_json["ready"].values()) else "draft"
    row.updated_by_user_id = int(actor.id)
    row.updated_at = datetime.now(UTC)
    db.add(row)
    db.flush()
    ready = [sufficiency.USE_LABELS[u] for u, ok in row.sufficiency_json["ready"].items() if ok]
    work_log.record(
        db,
        employee=EMPLOYEE_A,
        kind="observation",
        title=f"事实表「{title}」{'建立' if created else f'更新到 v{row.version}'}:够用的用途 {'、'.join(ready) or '暂无'}",
        why="",
        store_code=store_code,
        subject=f"factsheet|{product_line}|{sku or ''}",
        detail={"sheet_id": str(row.id), "ready": row.sufficiency_json["ready"], "version": row.version},
        source="human",
        actor_user_id=int(actor.id),
    )
    return row


def judge_sheet(db: Session, *, sheet_id: UUID, with_model: bool = True, call=None) -> AmzFactSheet:
    row = db.get(AmzFactSheet, sheet_id)
    if row is None:
        raise AmzServiceError("fact sheet not found", status_code=404, code="amz_fact_sheet_not_found")
    row.sufficiency_json = sufficiency.judge(row.facts_json or {}, product_line=row.product_line, title=row.title, org_id=_org_for(row.store_code), with_model=with_model, call=call)
    row.status = "ready" if all(row.sufficiency_json["ready"].values()) else "draft"
    db.add(row)
    db.flush()
    return row


def ready_for(db: Session, *, product_line: str, use: str, store_code: str | None = None, sku: str | None = None) -> AmzFactSheet | None:
    """给员工用:这条产品线(最具体的那份)在这个用途上够不够;不够返回 None——不写不画。"""
    candidates = [scope_key(product_line, store_code, sku), scope_key(product_line, store_code, None), scope_key(product_line, None, None)]
    for key in candidates:
        row = db.scalar(select(AmzFactSheet).where(AmzFactSheet.scope_key == key))
        if row is not None:
            return row if sufficiency.is_ready(row.sufficiency_json, use) else None
    return None


__all__ = ["FACT_FIELDS", "PRODUCT_LINES", "judge_sheet", "list_sheets", "normalize_facts", "ready_for", "scope_key", "upsert_sheet", "view"]
