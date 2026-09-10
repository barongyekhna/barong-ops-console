"""M 系列 · 出货成本明细的业务逻辑。

铁律:
- 价格是事件,不是属性:改价一律新增一行,永不 UPDATE 老行;
- 缺价绝不当 0 算:任何一行没价,合计就是 None,不是一个看着完整的假数字;
- 成本读的是**生产那一刻冻结的快照**,不在出货时回头查价;
- 所有查询显式带 ``factory_org_id``。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....models.user import User
from ....services.permission_service import user_has_permission
from ....core.roles import is_owner_role, is_super_admin_role
from ....services.data_isolation import without_org_data_isolation
from ..inventory import models as M
from ..inventory import service as inv
from ..inventory.service import FactoryContext, MfgError, MfgNotFound
from . import models as C
from . import pricing
from . import schemas as S
from .fifo import Batch, ZERO, draw, q_money, q_qty

PERMISSION_READ = "mfg.cost.read"
PERMISSION_PRICE = "mfg.cost.price"


def _today() -> date:
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------- 门禁


def user_may_access(
    user: User,
    ctx: FactoryContext,
    db: Session | None = None,
    action: str = "read",
) -> bool:
    """成本的门,形状照抄库存那道(``inventory.service.user_may_access``),但**认的是
    另一对权限码**。

    成本数据和库存数量不是一个密级:它带着每一家供应商的报价,和每个产品的毛利。
    会数箱子的人不该自动看见公司赚多少——所以这里绝不接受 ``mfg.inventory.*``。
    """
    if is_owner_role(user.role):
        return True
    if is_super_admin_role(user.role):
        return (user.organization_id or "") == ctx.factory_org_id
    if db is None:
        return False
    from ....models.org_membership import OrgMembershipRecord

    with without_org_data_isolation():
        member = db.scalar(
            select(OrgMembershipRecord.membership_id).where(
                OrgMembershipRecord.user_id == str(user.id),
                OrgMembershipRecord.org_id == ctx.factory_org_id,
                OrgMembershipRecord.status == "active",
            )
        )
    if member is None:
        return False
    # 定价权蕴含查看权
    if user_has_permission(db, user, PERMISSION_PRICE):
        return True
    return action != "price" and user_has_permission(db, user, PERMISSION_READ)


# ---------------------------------------------------------------- 小工具


def _get_product(db: Session, ctx: FactoryContext, product_id: UUID) -> M.MfgItem:
    item = inv._get_item(db, ctx, product_id)
    if item.kind != M.KIND_PRODUCT:
        raise MfgError("只有成品才有出货成本明细")
    return item


def _actor(db: Session, user: User) -> tuple[str, str]:
    return str(user.id), inv._actor_name(db, user)


# ---------------------------------------------------------------- 工序库


def list_processes(
    db: Session, ctx: FactoryContext, *, include_archived: bool = False
) -> S.LaborProcessListResponse:
    stmt = select(C.MfgLaborProcess).where(
        C.MfgLaborProcess.factory_org_id == ctx.factory_org_id
    )
    if not include_archived:
        stmt = stmt.where(C.MfgLaborProcess.is_archived.is_(False))
    processes = list(
        db.scalars(stmt.order_by(C.MfgLaborProcess.position, C.MfgLaborProcess.name))
    )
    process_ids = [p.id for p in processes]

    rates = pricing.current_labor_rates(
        db, ctx.factory_org_id, process_ids, on=_today()
    )
    rate_dates = _current_rate_dates(db, ctx, process_ids)
    usage = dict(
        db.execute(
            select(C.MfgLaborLine.process_id, func.count())
            .where(C.MfgLaborLine.factory_org_id == ctx.factory_org_id)
            .group_by(C.MfgLaborLine.process_id)
        ).all()
    )

    items = [
        S.LaborProcessRead(
            id=p.id,
            name=p.name,
            note=p.note,
            position=p.position,
            is_archived=p.is_archived,
            rate=rates.get(p.id),
            rate_effective_date=rate_dates.get(p.id),
            used_by_product_count=int(usage.get(p.id, 0)),
        )
        for p in processes
    ]
    return S.LaborProcessListResponse(items=items, total=len(items))


def _current_rate_dates(
    db: Session, ctx: FactoryContext, process_ids: list[UUID]
) -> dict[UUID, date]:
    if not process_ids:
        return {}
    rows = db.execute(
        select(C.MfgLaborRate.process_id, C.MfgLaborRate.effective_date)
        .where(
            C.MfgLaborRate.factory_org_id == ctx.factory_org_id,
            C.MfgLaborRate.process_id.in_(process_ids),
            C.MfgLaborRate.effective_date <= _today(),
        )
        .order_by(
            C.MfgLaborRate.process_id,
            C.MfgLaborRate.effective_date,
            C.MfgLaborRate.created_at,
        )
    ).all()
    return {process_id: eff for process_id, eff in rows}


def create_process(
    db: Session, ctx: FactoryContext, *, user: User, payload: S.LaborProcessCreate
) -> C.MfgLaborProcess:
    name = payload.name.strip()
    exists = db.scalar(
        select(C.MfgLaborProcess.id).where(
            C.MfgLaborProcess.factory_org_id == ctx.factory_org_id,
            C.MfgLaborProcess.name == name,
        )
    )
    if exists is not None:
        raise MfgError(f"工序「{name}」已存在")

    max_position = db.scalar(
        select(func.coalesce(func.max(C.MfgLaborProcess.position), 0)).where(
            C.MfgLaborProcess.factory_org_id == ctx.factory_org_id
        )
    )
    process = C.MfgLaborProcess(
        factory_org_id=ctx.factory_org_id,
        name=name,
        note=payload.note,
        position=int(max_position or 0) + 1,
    )
    db.add(process)
    db.flush()

    user_id, actor_name = _actor(db, user)
    db.add(
        C.MfgLaborRate(
            factory_org_id=ctx.factory_org_id,
            process_id=process.id,
            rate=q_money(payload.rate),
            effective_date=payload.effective_date or _today(),
            created_by_user_id=user_id,
            created_by_name=actor_name,
        )
    )
    inv._commit(db)
    db.refresh(process)
    return process


def patch_process(
    db: Session, ctx: FactoryContext, process_id: UUID, patch: S.LaborProcessPatch
) -> C.MfgLaborProcess:
    process = _get_process(db, ctx, process_id)
    data = patch.model_dump(exclude_unset=True)
    new_name = data.get("name")
    if new_name is not None:
        new_name = new_name.strip()
        clash = db.scalar(
            select(C.MfgLaborProcess.id).where(
                C.MfgLaborProcess.factory_org_id == ctx.factory_org_id,
                C.MfgLaborProcess.name == new_name,
                C.MfgLaborProcess.id != process.id,
            )
        )
        if clash is not None:
            raise MfgError(f"工序「{new_name}」已存在")
        data["name"] = new_name
    for key, value in data.items():
        setattr(process, key, value)
    inv._commit(db)
    db.refresh(process)
    return process


def _get_process(
    db: Session, ctx: FactoryContext, process_id: UUID
) -> C.MfgLaborProcess:
    process = db.scalar(
        select(C.MfgLaborProcess).where(
            C.MfgLaborProcess.id == process_id,
            C.MfgLaborProcess.factory_org_id == ctx.factory_org_id,
        )
    )
    if process is None:
        raise MfgNotFound("工序不存在")
    return process


def add_labor_rate(
    db: Session,
    ctx: FactoryContext,
    process_id: UUID,
    *,
    user: User,
    payload: S.LaborRateCreate,
) -> C.MfgLaborRate:
    """涨工资 = 加一行,老行一个字不动。以后能看到这道工序的工价曲线。"""
    process = _get_process(db, ctx, process_id)
    user_id, actor_name = _actor(db, user)
    rate = C.MfgLaborRate(
        factory_org_id=ctx.factory_org_id,
        process_id=process.id,
        rate=q_money(payload.rate),
        effective_date=payload.effective_date or _today(),
        note=payload.note,
        created_by_user_id=user_id,
        created_by_name=actor_name,
    )
    db.add(rate)
    inv._commit(db)
    db.refresh(rate)
    return rate


def list_labor_rates(
    db: Session, ctx: FactoryContext, process_id: UUID
) -> list[C.MfgLaborRate]:
    _get_process(db, ctx, process_id)
    return list(
        db.scalars(
            select(C.MfgLaborRate)
            .where(
                C.MfgLaborRate.factory_org_id == ctx.factory_org_id,
                C.MfgLaborRate.process_id == process_id,
            )
            .order_by(
                C.MfgLaborRate.effective_date.desc(),
                C.MfgLaborRate.created_at.desc(),
            )
        )
    )


# ---------------------------------------------------------------- 产品挂接工序


def get_product_labor(
    db: Session, ctx: FactoryContext, product_id: UUID
) -> S.ProductLaborRead:
    product = _get_product(db, ctx, product_id)
    pairs = pricing.load_labor_lines(db, ctx.factory_org_id, product.id)
    rates = pricing.current_labor_rates(
        db, ctx.factory_org_id, [p.id for _, p in pairs], on=_today()
    )
    return S.ProductLaborRead(
        product_id=product.id,
        lines=[
            S.LaborLineRead(
                id=line.id,
                process_id=process.id,
                process_name=process.name,
                mode=line.mode,
                qty=line.qty,
                rate=rates.get(process.id),
                position=line.position,
            )
            for line, process in pairs
        ],
    )


def replace_product_labor(
    db: Session, ctx: FactoryContext, product_id: UUID, payload: S.LaborReplace
) -> S.ProductLaborRead:
    """整体替换,照 ``inventory.service.replace_bom`` 的路子。"""
    product = _get_product(db, ctx, product_id)
    process_ids = [line.process_id for line in payload.lines]
    if process_ids:
        found = set(
            db.scalars(
                select(C.MfgLaborProcess.id).where(
                    C.MfgLaborProcess.factory_org_id == ctx.factory_org_id,
                    C.MfgLaborProcess.id.in_(process_ids),
                )
            )
        )
        missing = [str(p) for p in process_ids if p not in found]
        if missing:
            raise MfgNotFound(f"工序不存在:{'、'.join(missing)}")

    for existing in db.scalars(
        select(C.MfgLaborLine).where(
            C.MfgLaborLine.factory_org_id == ctx.factory_org_id,
            C.MfgLaborLine.product_id == product.id,
        )
    ):
        db.delete(existing)
    db.flush()

    for position, line in enumerate(payload.lines):
        db.add(
            C.MfgLaborLine(
                factory_org_id=ctx.factory_org_id,
                product_id=product.id,
                process_id=line.process_id,
                mode=line.mode,
                qty=q_qty(line.qty),
                position=position,
            )
        )
    inv._commit(db)
    return get_product_labor(db, ctx, product.id)


# ---------------------------------------------------------------- 价格事件


def set_sale_price(
    db: Session,
    ctx: FactoryContext,
    product_id: UUID,
    *,
    user: User,
    payload: S.SalePriceCreate,
) -> C.MfgSalePrice:
    """定出厂价。成本是算出来的,出厂价是人定的——只有厂长和 owner 说了算。"""
    product = _get_product(db, ctx, product_id)
    user_id, actor_name = _actor(db, user)
    row = C.MfgSalePrice(
        factory_org_id=ctx.factory_org_id,
        product_id=product.id,
        unit_price=q_money(payload.unit_price),
        effective_date=payload.effective_date or _today(),
        note=payload.note,
        created_by_user_id=user_id,
        created_by_name=actor_name,
    )
    db.add(row)
    inv._commit(db)
    db.refresh(row)
    return row


def list_sale_prices(
    db: Session, ctx: FactoryContext, product_id: UUID
) -> list[C.MfgSalePrice]:
    _get_product(db, ctx, product_id)
    return list(
        db.scalars(
            select(C.MfgSalePrice)
            .where(
                C.MfgSalePrice.factory_org_id == ctx.factory_org_id,
                C.MfgSalePrice.product_id == product_id,
            )
            .order_by(
                C.MfgSalePrice.effective_date.desc(),
                C.MfgSalePrice.created_at.desc(),
            )
        )
    )


def set_reference_price(
    db: Session,
    ctx: FactoryContext,
    item_id: UUID,
    *,
    user: User,
    payload: S.ReferencePriceCreate,
) -> C.MfgItemPrice:
    """给没入过库的物料记一个参考价。入过库的价格在流水上,不走这里。"""
    item = inv._get_item(db, ctx, item_id)
    user_id, actor_name = _actor(db, user)
    row = C.MfgItemPrice(
        factory_org_id=ctx.factory_org_id,
        item_id=item.id,
        unit_price=q_money(payload.unit_price),
        freight_per_unit=q_money(payload.freight_per_unit),
        source=payload.source,
        effective_date=payload.effective_date or _today(),
        note=payload.note,
        created_by_user_id=user_id,
        created_by_name=actor_name,
    )
    db.add(row)
    inv._commit(db)
    db.refresh(row)
    return row


# ---------------------------------------------------------------- 成品 FIFO


@dataclass(frozen=True)
class ProductHead:
    """成品队列的队头:下一次发货会发掉的那一批,以及它当初的成本。"""

    document_id: UUID | None
    doc_no: str | None
    snapshot: dict[str, Any] | None
    produced_qty: Decimal
    remaining: Decimal
    unit_cost: Decimal | None
    crosses_batches: bool


def _product_batches(
    db: Session, ctx: FactoryContext, product_id: UUID
) -> list[tuple[Batch, M.MfgDocument]]:
    """成品批次:每张生产单的产出就是一批,单价 = 那张单冻结的单位成本。

    这样成品和物料共用同一套先进先出的算法——不必为"成品也要 FIFO"再写一遍。
    """
    rows = db.execute(
        select(M.MfgMovement, M.MfgDocument)
        .join(M.MfgDocument, M.MfgDocument.id == M.MfgMovement.document_id)
        .where(
            M.MfgMovement.factory_org_id == ctx.factory_org_id,
            M.MfgMovement.item_id == product_id,
            M.MfgMovement.qty_delta > 0,
        )
        .order_by(M.MfgMovement.created_at, M.MfgMovement.id)
    ).all()

    result: list[tuple[Batch, M.MfgDocument]] = []
    for movement, document in rows:
        snapshot = (document.payload_json or {}).get("cost_snapshot") or {}
        raw_cost = snapshot.get("unit_cost")
        result.append(
            (
                Batch(
                    movement_id=movement.id,
                    qty=q_qty(movement.qty_delta),
                    unit_price=None if raw_cost in (None, "") else Decimal(raw_cost),
                    unit_freight=None,
                    created_at=movement.created_at,
                ),
                document,
            )
        )
    return result


def product_head(
    db: Session, ctx: FactoryContext, product_id: UUID, *, need: Decimal
) -> ProductHead:
    """先进先出定位:这次要发 ``need``,吃的是哪一批(或哪几批)。"""
    pairs = _product_batches(db, ctx, product_id)
    if not pairs:
        return ProductHead(None, None, None, ZERO, ZERO, None, False)

    batches = [batch for batch, _ in pairs]
    by_movement = {batch.movement_id: doc for batch, doc in pairs}
    consumed = pricing.load_consumed(db, ctx.factory_org_id, [product_id]).get(
        product_id, ZERO
    )
    result = draw(batches, consumed=consumed, need=need)
    if not result.rows:
        return ProductHead(None, None, None, ZERO, ZERO, None, False)

    head_row = result.rows[0]
    head_doc = by_movement.get(head_row.movement_id)
    snapshot = (head_doc.payload_json or {}).get("cost_snapshot") if head_doc else None
    produced = next(
        (b.qty for b in batches if b.movement_id == head_row.movement_id), ZERO
    )
    return ProductHead(
        document_id=head_doc.id if head_doc else None,
        doc_no=head_doc.doc_no if head_doc else None,
        snapshot=snapshot or None,
        produced_qty=produced,
        remaining=head_row.qty,
        unit_cost=result.unit_price,
        crosses_batches=result.crosses_batches,
    )


# ---------------------------------------------------------------- 成本表


def _valid_days(has_volatile: bool) -> int:
    return C.VALID_DAYS_VOLATILE if has_volatile else C.VALID_DAYS_NORMAL


def _lines_from_snapshot(snapshot: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    return list(snapshot.get("materials") or []), list(snapshot.get("labor") or [])


def _material_reads(rows: list[dict[str, Any]]) -> list[S.CostLineRead]:
    return [
        S.CostLineRead(
            kind="material",
            code=row.get("code"),
            name=row["name"],
            unit=row["unit"],
            mode=row.get("mode"),
            bom_qty=row.get("bom_qty"),
            qty=row["qty"],
            unit_price=row.get("unit_price"),
            unit_freight=row.get("unit_freight"),
            line_material=row.get("line_material"),
            line_freight=row.get("line_freight"),
            missing_price=bool(row.get("missing_price")),
            price_source=row.get("price_source"),
            crosses_batches=bool(row.get("crosses_batches")),
            extrapolated=row.get("extrapolated"),
            estimated_price=bool(row.get("estimated_price")),
            batches=row.get("batches") or [],
        )
        for row in rows
    ]


def _labor_reads(rows: list[dict[str, Any]]) -> list[S.CostLineRead]:
    return [
        S.CostLineRead(
            kind="labor",
            name=row["name"],
            unit="工序",
            mode=row.get("mode"),
            qty=row["qty"],
            unit_price=row.get("rate"),
            line_total=row.get("line_total"),
            missing_price=bool(row.get("missing_rate")),
        )
        for row in rows
    ]


def _volatile_flag(
    db: Session, ctx: FactoryContext, materials: list[dict[str, Any]]
) -> bool:
    """全表取最短有效期:只要用到一个波动料,整张表就是 7 天。"""
    item_ids = [
        UUID(row["item_id"]) for row in materials if row.get("item_id")
    ]
    if not item_ids:
        return False
    hit = db.scalar(
        select(M.MfgItem.id)
        .where(
            M.MfgItem.factory_org_id == ctx.factory_org_id,
            M.MfgItem.id.in_(item_ids),
            M.MfgItem.is_volatile.is_(True),
        )
        .limit(1)
    )
    return hit is not None


def preview_sheet(
    db: Session,
    ctx: FactoryContext,
    *,
    product_id: UUID,
    batch_qty: Decimal,
    sale_price_override: Decimal | None = None,
) -> S.CostSheetPreview:
    """实时算一份成本表。**不落库**——改批量数就重算,不会留下一堆垃圾快照。

    两种成色:
    - **actual**:有成品库存 → 明细直接读队头那批生产时冻结的快照。那批花了多少钱
      是既成事实,不重算。明细对应的是**生产时的批量**,用户输入的出货量只影响
      "本单总额"这一行——不去伪造一份"如果当时生产 60 件"的明细。
    - **estimate**:没生产过/已发完 → 按当前物料队头实时算,整张表标"预估"。
    """
    product = _get_product(db, ctx, product_id)
    qty = q_qty(batch_qty)
    stock = inv.stock_of(db, ctx, [product.id])[product.id]

    head = product_head(db, ctx, product.id, need=qty) if stock > ZERO else None
    use_actual = head is not None and head.snapshot is not None

    if use_actual:
        snapshot = head.snapshot or {}
        materials_raw, labor_raw = _lines_from_snapshot(snapshot)
        detail_batch_qty = Decimal(str(snapshot.get("batch_qty") or qty))
        basis: str = C.BASIS_ACTUAL
        unit_cost = head.unit_cost if head else None
        totals = S.CostTotals(
            material_total=snapshot.get("material_total"),
            freight_total=snapshot.get("freight_total"),
            labor_total=snapshot.get("labor_total"),
            unit_cost=unit_cost,
            missing_price_count=int(snapshot.get("missing_price_count") or 0),
        )
    else:
        requirements = inv._requirements(db, ctx, product, qty, lock=False)
        snapshot = pricing.build_cost_snapshot(
            db,
            ctx.factory_org_id,
            product_id=product.id,
            batch_qty=qty,
            requirements=requirements,
        )
        materials_raw, labor_raw = _lines_from_snapshot(snapshot)
        detail_batch_qty = qty
        basis = C.BASIS_ESTIMATE
        totals = S.CostTotals(
            material_total=snapshot.get("material_total"),
            freight_total=snapshot.get("freight_total"),
            labor_total=snapshot.get("labor_total"),
            unit_cost=snapshot.get("unit_cost"),
            missing_price_count=int(snapshot.get("missing_price_count") or 0),
        )

    has_volatile = _volatile_flag(db, ctx, materials_raw)
    valid_days = _valid_days(has_volatile)

    sale_price = sale_price_override
    if sale_price is None:
        sale_price = pricing.current_sale_price(
            db, ctx.factory_org_id, product.id, on=_today()
        )
    sale_price = None if sale_price is None else q_money(sale_price)

    unit_margin = None
    margin_rate = None
    batch_total = None
    if sale_price is not None:
        batch_total = q_money(sale_price * qty)
        if totals.unit_cost is not None:
            unit_margin = q_money(sale_price - totals.unit_cost)
            if sale_price > ZERO:
                margin_rate = q_money(unit_margin / sale_price * Decimal("100"))

    return S.CostSheetPreview(
        product_id=product.id,
        product_code=product.code,
        product_name=product.name,
        product_unit=product.unit,
        batch_qty=qty,
        basis=basis,
        source_document_id=head.document_id if use_actual and head else None,
        source_doc_no=head.doc_no if use_actual and head else None,
        stock=stock,
        materials=_material_reads(materials_raw),
        labor=_labor_reads(labor_raw),
        totals=totals,
        sale_price=sale_price,
        unit_margin=unit_margin,
        margin_rate=margin_rate,
        batch_total=batch_total,
        has_volatile=has_volatile,
        expires_on=_expiry(valid_days),
        valid_days=valid_days,
    )


def _expiry(valid_days: int) -> date:
    from datetime import timedelta

    return _today() + timedelta(days=valid_days)


def list_product_costs(
    db: Session, ctx: FactoryContext, *, include_archived: bool = False
) -> S.ProductCostListResponse:
    """列表页:每个成品一行。已归档的默认不出现。"""
    products = inv.list_items(
        db, ctx, kind=M.KIND_PRODUCT, include_archived=include_archived
    )
    stocks = inv.stock_of(db, ctx, [p.id for p in products])
    bom_counts = dict(
        db.execute(
            select(M.MfgBomLine.product_id, func.count())
            .where(M.MfgBomLine.factory_org_id == ctx.factory_org_id)
            .group_by(M.MfgBomLine.product_id)
        ).all()
    )
    labor_counts = dict(
        db.execute(
            select(C.MfgLaborLine.product_id, func.count())
            .where(C.MfgLaborLine.factory_org_id == ctx.factory_org_id)
            .group_by(C.MfgLaborLine.product_id)
        ).all()
    )

    rows: list[S.ProductCostRow] = []
    for product in products:
        stock = stocks.get(product.id, ZERO)
        sale_price = pricing.current_sale_price(
            db, ctx.factory_org_id, product.id, on=_today()
        )
        unit_cost: Decimal | None = None
        missing = 0
        basis = C.BASIS_ESTIMATE

        if stock > ZERO:
            head = product_head(db, ctx, product.id, need=Decimal("1"))
            if head.snapshot is not None:
                basis = C.BASIS_ACTUAL
                unit_cost = head.unit_cost
                missing = int(head.snapshot.get("missing_price_count") or 0)

        if unit_cost is None and bom_counts.get(product.id):
            # 没生产过也给个预估,列表页不能一片空白
            try:
                preview = preview_sheet(
                    db, ctx, product_id=product.id, batch_qty=Decimal("1")
                )
            except MfgError:
                preview = None
            if preview is not None:
                unit_cost = preview.totals.unit_cost
                missing = preview.totals.missing_price_count

        margin_rate = None
        if sale_price is not None and unit_cost is not None and sale_price > ZERO:
            margin_rate = q_money(
                (sale_price - unit_cost) / sale_price * Decimal("100")
            )

        rows.append(
            S.ProductCostRow(
                product_id=product.id,
                code=product.code,
                name=product.name,
                unit=product.unit,
                stock=stock,
                basis=basis,
                unit_cost=unit_cost,
                sale_price=sale_price,
                margin_rate=margin_rate,
                missing_price_count=missing,
                bom_line_count=int(bom_counts.get(product.id, 0)),
                labor_line_count=int(labor_counts.get(product.id, 0)),
            )
        )
    return S.ProductCostListResponse(items=rows, total=len(rows))


def create_sheet(
    db: Session, ctx: FactoryContext, *, user: User, payload: S.CostSheetCreate
) -> C.MfgCostSheet:
    """定稿:把当前这份实时结果冻成快照。

    快照行存的是**抄下来的文本**而不是外键:三个月后物料改了名、BOM 换了配方、
    价格翻了倍,这一份还是发出去时的样子。发出去的数字再也不能变。
    """
    preview = preview_sheet(
        db,
        ctx,
        product_id=payload.product_id,
        batch_qty=payload.batch_qty,
        sale_price_override=payload.sale_price_override,
    )
    user_id, actor_name = _actor(db, user)

    sheet = C.MfgCostSheet(
        factory_org_id=ctx.factory_org_id,
        sheet_no=inv._next_doc_no(db, ctx, M.DOC_COST_SHEET),
        product_id=preview.product_id,
        product_code=preview.product_code,
        product_name=preview.product_name,
        product_unit=preview.product_unit,
        batch_qty=preview.batch_qty,
        basis=preview.basis,
        source_document_id=preview.source_document_id,
        expires_on=preview.expires_on,
        has_volatile=preview.has_volatile,
        missing_price_count=preview.totals.missing_price_count,
        material_total=preview.totals.material_total,
        freight_total=preview.totals.freight_total,
        labor_total=preview.totals.labor_total,
        unit_cost=preview.totals.unit_cost,
        sale_price=preview.sale_price,
        actor_user_id=user_id,
        actor_name=actor_name,
        note=payload.note,
    )
    db.add(sheet)
    db.flush()

    position = 0
    for line in preview.materials:
        db.add(
            C.MfgCostSheetLine(
                factory_org_id=ctx.factory_org_id,
                sheet_id=sheet.id,
                kind=C.LINE_KIND_MATERIAL,
                position=position,
                code=line.code,
                name=line.name,
                unit=line.unit,
                qty=line.qty,
                unit_price=line.unit_price,
                unit_freight=line.unit_freight,
                line_total=line.line_material,
                is_missing_price=line.missing_price,
                mode=line.mode,
                batch_breakdown=[b.model_dump(mode="json") for b in line.batches]
                or None,
            )
        )
        position += 1
    for line in preview.labor:
        db.add(
            C.MfgCostSheetLine(
                factory_org_id=ctx.factory_org_id,
                sheet_id=sheet.id,
                kind=C.LINE_KIND_LABOR,
                position=position,
                code=None,
                name=line.name,
                unit=line.unit,
                qty=line.qty,
                unit_price=line.unit_price,
                line_total=line.line_total,
                is_missing_price=line.missing_price,
                mode=line.mode,
            )
        )
        position += 1

    inv._commit(db)
    db.refresh(sheet)
    return sheet


def get_sheet(db: Session, ctx: FactoryContext, sheet_id: UUID) -> S.CostSheetDetail:
    sheet = db.scalar(
        select(C.MfgCostSheet).where(
            C.MfgCostSheet.id == sheet_id,
            C.MfgCostSheet.factory_org_id == ctx.factory_org_id,
        )
    )
    if sheet is None:
        raise MfgNotFound("成本表不存在")

    lines = list(
        db.scalars(
            select(C.MfgCostSheetLine)
            .where(C.MfgCostSheetLine.sheet_id == sheet.id)
            .order_by(C.MfgCostSheetLine.position)
        )
    )
    shares = list(
        db.scalars(
            select(C.MfgCostSheetShare)
            .where(C.MfgCostSheetShare.sheet_id == sheet.id)
            .order_by(C.MfgCostSheetShare.created_at.desc())
        )
    )

    detail = S.CostSheetDetail.model_validate(sheet)
    detail.materials = [
        S.CostLineRead(
            kind="material",
            code=line.code,
            name=line.name,
            unit=line.unit,
            mode=line.mode,
            qty=line.qty,
            unit_price=line.unit_price,
            unit_freight=line.unit_freight,
            line_material=line.line_total,
            missing_price=line.is_missing_price,
            batches=line.batch_breakdown or [],
        )
        for line in lines
        if line.kind == C.LINE_KIND_MATERIAL
    ]
    detail.labor = [
        S.CostLineRead(
            kind="labor",
            name=line.name,
            unit=line.unit,
            mode=line.mode,
            qty=line.qty,
            unit_price=line.unit_price,
            line_total=line.line_total,
            missing_price=line.is_missing_price,
        )
        for line in lines
        if line.kind == C.LINE_KIND_LABOR
    ]
    detail.shares = [S.CostShareRead.model_validate(s) for s in shares]
    return detail


def list_sheets(
    db: Session, ctx: FactoryContext, *, product_id: UUID | None = None, limit: int = 50
) -> S.CostSheetListResponse:
    stmt = select(C.MfgCostSheet).where(
        C.MfgCostSheet.factory_org_id == ctx.factory_org_id
    )
    if product_id is not None:
        stmt = stmt.where(C.MfgCostSheet.product_id == product_id)
    total = db.scalar(
        select(func.count()).select_from(stmt.subquery())
    )
    rows = list(
        db.scalars(stmt.order_by(C.MfgCostSheet.created_at.desc()).limit(limit))
    )
    return S.CostSheetListResponse(
        items=[S.CostSheetRead.model_validate(row) for row in rows],
        total=int(total or 0),
    )
