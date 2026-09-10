"""M 系列给制造公司主页的三张卡：库存总览、生产能力/缺料、今日单据。

规矩与 M 模块一致：
- 门禁与库存接口同一道（`service.user_may_access`：owner / 制造超管 / 带权限码的制造公司成员）；不过门就返回 None，卡不出现。
  否则会出现「卡看得见、接口 403」。
- 只 select。库存 = 流水求和（`service.stock_of`），一次算完全部物料，再在内存里推能力。
- 「缺料」不问人：对每个有 BOM 的成品，按 BOM 和现有库存算「最多还能产多少」，
  卡死（0）的就是缺料，卡在哪个配件也一并算出来。
- 「今日」按工厂时间（吉林，Asia/Shanghai），卡片上标「工厂时间」。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, time
from decimal import ROUND_FLOOR, Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models.user import User
from ..home.schemas import HomeCardItem, HomeCardRead
from .inventory import models as M
from .inventory import service

MODULE_KEY = "mfg.inventory"
MODULE_HREF = "/mfg-inventory"
FACTORY_TZ = ZoneInfo("Asia/Shanghai")
FACTORY_TZ_LABEL = "工厂时间 UTC+8"
DOC_TYPE_LABEL = {
    M.DOC_RECEIPT: "入库",
    M.DOC_PRODUCTION: "生产",
    M.DOC_SHIPMENT: "发货",
    M.DOC_ADJUSTMENT: "盘点调整",
}
KIND_LABEL = {M.KIND_PART: "配件", M.KIND_PRODUCT: "成品"}
LIST_LIMIT = 8
ZERO = Decimal("0")


def _factory(db: Session, workspace_key: str, user: User) -> service.FactoryContext | None:
    """调用者必须就是那家唯一的制造公司，且过 M 的角色门。"""
    try:
        ctx = service.resolve_factory_context(db)
    except service.FactoryNotConfigured:
        return None
    if ctx.factory_org_id != workspace_key:
        return None
    if not service.user_may_access(user, ctx, db=db):
        return None
    return ctx


def factory_today_start(now: datetime | None = None) -> datetime:
    current = (now or datetime.now(UTC)).astimezone(FACTORY_TZ)
    return datetime.combine(current.date(), time.min, tzinfo=FACTORY_TZ)


def _num(value: Decimal) -> str:
    """Decimal 转成不带多余零的字符串，前端直接显示。"""
    text = format(value.normalize(), "f")
    return text if text != "-0" else "0"


def _floor(value: Decimal) -> Decimal:
    return value.to_integral_value(rounding=ROUND_FLOOR)


# ---------------------------------------------------------------- 库存总览


def load_stock_card(
    db: Session,
    *,
    workspace_key: str,
    user: User,
    permission_keys: frozenset[str],
    is_full_access: bool,
    **_: Any,
) -> HomeCardRead | None:
    ctx = _factory(db, workspace_key, user)
    if ctx is None:
        return None
    items = service.list_items(db, ctx)
    stock = service.stock_of(db, ctx, [item.id for item in items])

    products = [item for item in items if item.kind == M.KIND_PRODUCT]
    parts = [item for item in items if item.kind == M.KIND_PART]
    zero = [item for item in items if stock.get(item.id, ZERO) <= ZERO]
    product_rows = sorted(products, key=lambda item: stock.get(item.id, ZERO), reverse=True)

    def row(item: M.MfgItem) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "code": item.code,
            "name": item.name,
            "kind": item.kind,
            "unit": item.unit,
            "stock": _num(stock.get(item.id, ZERO)),
        }

    return HomeCardRead(
        card_id="mfg-stock",
        module_key=MODULE_KEY,
        count=len(zero),
        items=[
            HomeCardItem(
                id=str(item.id),
                title=f"{item.name} 断货",
                subtitle=f"{KIND_LABEL.get(item.kind, item.kind)} · 现有 {_num(stock.get(item.id, ZERO))} {item.unit}",
                at=None,
                href=MODULE_HREF,
            )
            for item in zero[:5]
        ],
        freshness=datetime.now(UTC),
        actions=[],
        extra={
            "products": [row(item) for item in product_rows[:LIST_LIMIT]],
            "parts_total": len(parts),
            "products_total": len(products),
            "zero": [row(item) for item in zero[:LIST_LIMIT]],
            "zero_count": len(zero),
        },
        severity="warn" if zero else "ok",
    )


# ---------------------------------------------------------------- 生产能力 / 缺料


def _max_producible(mode: str, bom_qty: Decimal, available: Decimal) -> Decimal:
    """按一条 BOM 线，现有配件最多支撑多少成品。与 `service.required_for` 互为反函数。"""
    if available <= ZERO or bom_qty <= ZERO:
        return ZERO
    if mode == M.BOM_MODE_PER_UNIT:
        return _floor(available / bom_qty)
    # per_carton：每 bom_qty 件装一箱，available 个箱子最多装 available * bom_qty 件
    return _floor(available * bom_qty)


def load_capacity_card(
    db: Session,
    *,
    workspace_key: str,
    user: User,
    permission_keys: frozenset[str],
    is_full_access: bool,
    **_: Any,
) -> HomeCardRead | None:
    ctx = _factory(db, workspace_key, user)
    if ctx is None:
        return None
    items = {item.id: item for item in service.list_items(db, ctx, include_archived=True)}
    products = [item for item in items.values() if item.kind == M.KIND_PRODUCT and not item.is_archived]
    lines = db.execute(
        select(M.MfgBomLine)
        .where(M.MfgBomLine.factory_org_id == ctx.factory_org_id)
        .order_by(M.MfgBomLine.product_id, M.MfgBomLine.position)
    ).scalars().all()
    by_product: dict[UUID, list[M.MfgBomLine]] = defaultdict(list)
    for line in lines:
        by_product[line.product_id].append(line)
    stock = service.stock_of(db, ctx, [line.part_id for line in lines])

    rows: list[dict[str, Any]] = []
    no_bom: list[dict[str, Any]] = []
    for product in sorted(products, key=lambda item: item.code):
        product_lines = by_product.get(product.id, [])
        if not product_lines:
            no_bom.append({"id": str(product.id), "code": product.code, "name": product.name})
            continue
        best: Decimal | None = None
        blocker: M.MfgBomLine | None = None
        for line in product_lines:
            capacity = _max_producible(line.mode, line.qty, stock.get(line.part_id, ZERO))
            if best is None or capacity < best:
                best, blocker = capacity, line
        part = items.get(blocker.part_id) if blocker is not None else None
        rows.append(
            {
                "id": str(product.id),
                "code": product.code,
                "name": product.name,
                "unit": product.unit,
                "max_producible": _num(best or ZERO),
                "blocker_code": part.code if part else None,
                "blocker_name": part.name if part else None,
                "blocker_unit": part.unit if part else None,
                "blocker_available": _num(stock.get(blocker.part_id, ZERO)) if blocker else None,
            }
        )
    rows.sort(key=lambda item: Decimal(item["max_producible"]))
    blocked = [item for item in rows if Decimal(item["max_producible"]) <= ZERO]

    return HomeCardRead(
        card_id="mfg-capacity",
        module_key=MODULE_KEY,
        count=len(blocked),
        items=[
            HomeCardItem(
                id=item["id"],
                title=f"{item['name']} 最多可产 0 {item['unit']}",
                subtitle=(
                    f"卡在 {item['blocker_name']}（现有 {item['blocker_available']} {item['blocker_unit']}）"
                    if item["blocker_name"]
                    else "配件清单为空"
                ),
                at=None,
                href=MODULE_HREF,
            )
            for item in blocked[:5]
        ],
        freshness=datetime.now(UTC),
        actions=[],
        extra={"products": rows[:LIST_LIMIT], "no_bom": no_bom[:LIST_LIMIT], "blocked_count": len(blocked)},
        severity="warn" if blocked else "ok",
    )


# ---------------------------------------------------------------- 今日单据


def load_docs_card(
    db: Session,
    *,
    workspace_key: str,
    user: User,
    permission_keys: frozenset[str],
    is_full_access: bool,
    now: datetime | None = None,
    **_: Any,
) -> HomeCardRead | None:
    ctx = _factory(db, workspace_key, user)
    if ctx is None:
        return None
    day_start = factory_today_start(now)
    today_rows = db.execute(
        select(M.MfgDocument.doc_type, func.count())
        .where(
            M.MfgDocument.factory_org_id == ctx.factory_org_id,
            M.MfgDocument.created_at >= day_start,
        )
        .group_by(M.MfgDocument.doc_type)
    ).all()
    today = {doc_type: 0 for doc_type in M.ALLOWED_DOC_TYPES}
    for doc_type, count in today_rows:
        today[str(doc_type)] = int(count)
    recent, _ = service.list_documents(db, ctx, doc_type=None, item_id=None, limit=10, offset=0)

    def row(doc: M.MfgDocument) -> dict[str, Any]:
        return {
            "id": str(doc.id),
            "doc_no": doc.doc_no,
            "doc_type": doc.doc_type,
            "doc_type_label": DOC_TYPE_LABEL.get(doc.doc_type, doc.doc_type),
            "actor_name": doc.actor_name,
            "note": doc.note,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        }

    return HomeCardRead(
        card_id="mfg-docs",
        module_key=MODULE_KEY,
        count=sum(today.values()),
        items=[
            HomeCardItem(
                id=str(doc.id),
                title=f"{doc.doc_no} · {DOC_TYPE_LABEL.get(doc.doc_type, doc.doc_type)}",
                subtitle=" · ".join(part for part in (doc.actor_name, doc.note or "") if part),
                at=doc.created_at,
                href=MODULE_HREF,
            )
            for doc in recent[:5]
        ],
        freshness=datetime.now(UTC),
        actions=[],
        extra={
            "today": today,
            "today_total": sum(today.values()),
            "recent": [row(doc) for doc in recent],
            "tz": FACTORY_TZ_LABEL,
            "day_start": day_start.isoformat(),
        },
        severity="ok",
    )
