"""成本计算内核:把流水和工价换算成一份成本快照。

**依赖方向是单向的**:这里只 import ``inventory.models`` 和 ``cost.models``,绝不
import ``inventory.service``——因为反过来 ``inventory.service.production()`` 要调用
这里的 ``build_cost_snapshot``。两边互相 import 就死锁了。

成本冻结在**生产那一刻**:一批成品生产完,它花了多少钱是既成事实(那天领了哪几批
料、每批什么价、当天什么工价)。三个月后发货再回头算,料价早就变了,算出来的不是
这批货的成本,是一个假数字。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..inventory import models as M
from . import models as C
from .fifo import Batch, FifoDraw, ZERO, draw, q_money, q_qty

COST_SNAPSHOT_VERSION = 1


# ---------------------------------------------------------------- 取数


def load_batches(
    db: Session, factory_org_id: str, item_ids: Sequence[UUID]
) -> dict[UUID, list[Batch]]:
    """每个物料的入库批次,按时间升序。

    正向流水**全都要**,包括盘盈那种没有价格的:它照样占着队列位置、照样会被消耗。
    把无价批次过滤掉会让队头算错位,进而把老料的成本安到新料头上。
    """
    if not item_ids:
        return {}
    rows = db.execute(
        select(
            M.MfgMovement.item_id,
            M.MfgMovement.id,
            M.MfgMovement.qty_delta,
            M.MfgMovement.unit_price,
            M.MfgMovement.unit_freight,
            M.MfgMovement.price_is_estimated,
            M.MfgMovement.created_at,
        )
        .where(
            M.MfgMovement.factory_org_id == factory_org_id,
            M.MfgMovement.item_id.in_(list(set(item_ids))),
            M.MfgMovement.qty_delta > 0,
        )
        .order_by(M.MfgMovement.created_at, M.MfgMovement.id)
    ).all()
    result: dict[UUID, list[Batch]] = {item_id: [] for item_id in item_ids}
    for item_id, mv_id, qty, price, freight, estimated, created_at in rows:
        result.setdefault(item_id, []).append(
            Batch(
                movement_id=mv_id,
                qty=q_qty(qty),
                unit_price=None if price is None else q_money(price),
                unit_freight=None if freight is None else q_money(freight),
                created_at=created_at,
                is_estimated=bool(estimated),
            )
        )
    return result


def load_consumed(
    db: Session, factory_org_id: str, item_ids: Sequence[UUID]
) -> dict[UUID, Decimal]:
    """每个物料的历史累计消耗量(正数)。领料、发货、盘亏一视同仁。"""
    if not item_ids:
        return {}
    rows = db.execute(
        select(
            M.MfgMovement.item_id,
            func.coalesce(func.sum(M.MfgMovement.qty_delta), 0),
        )
        .where(
            M.MfgMovement.factory_org_id == factory_org_id,
            M.MfgMovement.item_id.in_(list(set(item_ids))),
            M.MfgMovement.qty_delta < 0,
        )
        .group_by(M.MfgMovement.item_id)
    ).all()
    result: dict[UUID, Decimal] = {item_id: ZERO for item_id in item_ids}
    for item_id, total in rows:
        result[item_id] = q_qty(abs(Decimal(str(total))))
    return result


def load_reference_prices(
    db: Session, factory_org_id: str, item_ids: Sequence[UUID], *, on: date
) -> dict[UUID, C.MfgItemPrice]:
    """从没入过库的物料的参考价——每个物料取 ``effective_date <= on`` 的最新一条。"""
    if not item_ids:
        return {}
    rows = db.scalars(
        select(C.MfgItemPrice)
        .where(
            C.MfgItemPrice.factory_org_id == factory_org_id,
            C.MfgItemPrice.item_id.in_(list(set(item_ids))),
            C.MfgItemPrice.effective_date <= on,
        )
        .order_by(
            C.MfgItemPrice.item_id,
            C.MfgItemPrice.effective_date,
            C.MfgItemPrice.created_at,
        )
    ).all()
    # 升序遍历,后写的覆盖先写的,留下的就是每个物料的最新一条
    return {row.item_id: row for row in rows}


def current_labor_rates(
    db: Session, factory_org_id: str, process_ids: Sequence[UUID], *, on: date
) -> dict[UUID, Decimal]:
    """每道工序在 ``on`` 那天的工价。改价是新增一行,所以"当前值"= 取最新一条。"""
    if not process_ids:
        return {}
    rows = db.execute(
        select(
            C.MfgLaborRate.process_id,
            C.MfgLaborRate.rate,
        )
        .where(
            C.MfgLaborRate.factory_org_id == factory_org_id,
            C.MfgLaborRate.process_id.in_(list(set(process_ids))),
            C.MfgLaborRate.effective_date <= on,
        )
        .order_by(
            C.MfgLaborRate.process_id,
            C.MfgLaborRate.effective_date,
            C.MfgLaborRate.created_at,
        )
    ).all()
    return {process_id: q_money(rate) for process_id, rate in rows}


def load_labor_lines(
    db: Session, factory_org_id: str, product_id: UUID
) -> list[tuple[C.MfgLaborLine, C.MfgLaborProcess]]:
    """产品挂接的工序,按 position 排。已归档的工序不再计入新表。"""
    rows = db.execute(
        select(C.MfgLaborLine, C.MfgLaborProcess)
        .join(C.MfgLaborProcess, C.MfgLaborProcess.id == C.MfgLaborLine.process_id)
        .where(
            C.MfgLaborLine.factory_org_id == factory_org_id,
            C.MfgLaborLine.product_id == product_id,
            C.MfgLaborProcess.is_archived.is_(False),
        )
        .order_by(C.MfgLaborLine.position, C.MfgLaborProcess.name)
    ).all()
    return [(line, process) for line, process in rows]


def current_sale_price(
    db: Session, factory_org_id: str, product_id: UUID, *, on: date
) -> Decimal | None:
    """产品当前出厂价。没定过价返回 None——**不要退回成本**,那会让人误以为
    这是个已经定过的价。"""
    row = db.scalars(
        select(C.MfgSalePrice)
        .where(
            C.MfgSalePrice.factory_org_id == factory_org_id,
            C.MfgSalePrice.product_id == product_id,
            C.MfgSalePrice.effective_date <= on,
        )
        .order_by(
            C.MfgSalePrice.effective_date.desc(),
            C.MfgSalePrice.created_at.desc(),
        )
        .limit(1)
    ).first()
    return None if row is None else q_money(row.unit_price)


# ---------------------------------------------------------------- 算


def material_line(
    *,
    item_id: UUID,
    code: str,
    name: str,
    unit: str,
    mode: str,
    bom_qty: Decimal,
    required: Decimal,
    batches: Sequence[Batch],
    consumed: Decimal,
    reference: C.MfgItemPrice | None,
) -> dict[str, Any]:
    """一行物料的成本。

    先按 FIFO 从库存批次取;一批都没入过库才退到参考价,并明确标成 ``reference``——
    参考价和真实批次价不是一回事,混在一起看会让人把"供应商说的"当成"我付过的"。
    """
    result: FifoDraw = draw(batches, consumed=consumed, need=required)

    unit_price = result.unit_price
    unit_freight = result.unit_freight
    source = "batch"
    breakdown = result.breakdown()

    if result.has_missing_price and not batches and reference is not None:
        unit_price = q_money(reference.unit_price)
        unit_freight = q_money(reference.freight_per_unit)
        source = "reference"
        breakdown = []

    missing = unit_price is None
    line_material = None if missing else q_money(required * unit_price)
    line_freight = (
        None if missing else q_money(required * (unit_freight or ZERO))
    )

    return {
        "item_id": str(item_id),
        "code": code,
        "name": name,
        "unit": unit,
        "mode": mode,
        "bom_qty": str(q_qty(bom_qty)),
        "qty": str(q_qty(required)),
        "unit_price": None if unit_price is None else str(unit_price),
        "unit_freight": None if unit_freight is None else str(unit_freight),
        "line_material": None if line_material is None else str(line_material),
        "line_freight": None if line_freight is None else str(line_freight),
        "missing_price": missing,
        "price_source": source,
        "crosses_batches": result.crosses_batches,
        "extrapolated": str(result.extrapolated),
        "estimated_price": result.has_estimated_price,
        "batches": breakdown,
    }


def labor_line(
    *,
    process_id: UUID,
    name: str,
    mode: str,
    qty: Decimal,
    rate: Decimal | None,
    batch_qty: Decimal,
) -> dict[str, Any]:
    """一道工序的成本。

    ``per_batch`` 是调机、开模摊销这类不随件数走的钱,必须除以批量:1000 件和 100 件
    摊下来天差地别,这一条直接决定小单能不能接。
    """
    missing = rate is None
    if missing:
        unit_cost = None
        line_total = None
    elif mode == C.LABOR_MODE_PER_BATCH:
        line_total = q_money(rate * qty)
        unit_cost = q_money(line_total / batch_qty) if batch_qty > ZERO else None
    else:
        unit_cost = q_money(rate * qty)
        line_total = q_money(unit_cost * batch_qty)

    return {
        "process_id": str(process_id),
        "name": name,
        "mode": mode,
        "qty": str(q_qty(qty)),
        "rate": None if rate is None else str(rate),
        "unit_cost": None if unit_cost is None else str(unit_cost),
        "line_total": None if line_total is None else str(line_total),
        "missing_rate": missing,
    }


def totals(
    materials: Sequence[dict[str, Any]],
    labor: Sequence[dict[str, Any]],
    batch_qty: Decimal,
) -> dict[str, Any]:
    """汇总。

    **只要有一行缺价,四个合计全部为 None**,不是把缺的那行当 0 加进去。给出一个
    看着完整的假总价,比明说"这里有 3 项没有价格"危险得多——前者会被拿去报价。
    """
    missing = [row for row in materials if row["missing_price"]]
    missing += [row for row in labor if row["missing_rate"]]
    if missing:
        return {
            "material_total": None,
            "freight_total": None,
            "labor_total": None,
            "unit_cost": None,
            "missing_price_count": len(missing),
        }

    material_total = q_money(
        sum((Decimal(row["line_material"]) for row in materials), ZERO)
    )
    freight_total = q_money(
        sum((Decimal(row["line_freight"]) for row in materials), ZERO)
    )
    labor_total = q_money(sum((Decimal(row["line_total"]) for row in labor), ZERO))
    grand = material_total + freight_total + labor_total
    unit_cost = q_money(grand / batch_qty) if batch_qty > ZERO else None

    return {
        "material_total": str(material_total),
        "freight_total": str(freight_total),
        "labor_total": str(labor_total),
        "unit_cost": None if unit_cost is None else str(unit_cost),
        "missing_price_count": 0,
    }


def build_cost_snapshot(
    db: Session,
    factory_org_id: str,
    *,
    product_id: UUID,
    batch_qty: Decimal,
    requirements: Sequence[Any],
    on: date | None = None,
) -> dict[str, Any]:
    """生产那一刻的成本快照,写进生产单的 ``payload_json.cost_snapshot``。

    ``requirements`` 是 ``inventory.service._requirements()`` 算出来的行(带
    ``item_id / code / name / unit / mode / bom_qty / required``),这里不重算需求量,
    免得两处算法悄悄分叉。

    **消耗量取的是这次领料之前的状态**:调用方必须在写负向流水之前调本函数,否则
    队头会被本次领料自己推着走,吃到的价就错了。
    """
    when = on or datetime.now(timezone.utc).date()
    item_ids = [row.item_id for row in requirements]

    batches = load_batches(db, factory_org_id, item_ids)
    consumed = load_consumed(db, factory_org_id, item_ids)
    references = load_reference_prices(db, factory_org_id, item_ids, on=when)

    materials = [
        material_line(
            item_id=row.item_id,
            code=row.code,
            name=row.name,
            unit=row.unit,
            mode=row.mode,
            bom_qty=row.bom_qty,
            required=row.required,
            batches=batches.get(row.item_id, []),
            consumed=consumed.get(row.item_id, ZERO),
            reference=references.get(row.item_id),
        )
        for row in requirements
    ]

    labor_pairs = load_labor_lines(db, factory_org_id, product_id)
    rates = current_labor_rates(
        db, factory_org_id, [process.id for _, process in labor_pairs], on=when
    )
    labor = [
        labor_line(
            process_id=process.id,
            name=process.name,
            mode=line.mode,
            qty=line.qty,
            rate=rates.get(process.id),
            batch_qty=batch_qty,
        )
        for line, process in labor_pairs
    ]

    snapshot = {
        "version": COST_SNAPSHOT_VERSION,
        "batch_qty": str(q_qty(batch_qty)),
        "computed_on": when.isoformat(),
        "materials": materials,
        "labor": labor,
    }
    snapshot.update(totals(materials, labor, batch_qty))
    return snapshot
