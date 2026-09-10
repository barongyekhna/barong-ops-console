"""M 系列 · 制造库存的业务逻辑。

铁律:
- 库存 = 流水求和,没有可手改的库存字段;
- 单据 + 流水在同一个事务里落地,要么全成要么全不成;
- 负库存拦死:生产/发货/调整任一项不足 → 整单拒绝并报差额;
- 所有查询显式带 ``factory_org_id``,不用 text() 裸 SQL。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any
from uuid import UUID

from pypinyin import Style, lazy_pinyin
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from ....core.roles import is_owner_role, is_super_admin_role
from ....models.organization import OrganizationRecord
from ....models.user import User
from ....services.data_isolation import without_org_data_isolation
from ....services.display_names import user_display_name
from . import models as M
from . import schemas as S

ORG_TYPE_FACTORY = "factory"
ZERO = Decimal("0")

# 物料大类预置(首次打开大类列表时按工厂落库;之后可增)。成品系列不预置——工厂无固定品类,
# 系列随第一个成品建立。
DEFAULT_PART_GROUPS: tuple[tuple[str, str], ...] = (
    ("HW", "五金件"),
    ("PL", "塑料件"),
    ("EL", "电子元件"),
    ("WD", "木制件"),
    ("FB", "布料织物"),
    ("CB", "线材"),
    ("BT", "电池"),
    ("PK", "包装材料"),
    ("LB", "标签印刷"),
    ("AX", "辅料耗材"),
)


class MfgError(ValueError):
    """请求本身不合法(422)。"""


class MfgNotFound(LookupError):
    """找不到对象(404)。"""


class FactoryNotConfigured(RuntimeError):
    """系统里没有(或不止一个)factory 组织(503)。"""


class InsufficientStock(MfgError):
    """负库存拦死。"""

    def __init__(self, message: str, shortages: list[S.RequirementRow]):
        super().__init__(message)
        self.shortages = shortages


@dataclass(frozen=True)
class FactoryContext:
    factory_org_id: str
    org_name: str


# ---------------------------------------------------------------- 工厂定位/门禁


def resolve_factory_context(db: Session) -> FactoryContext:
    """唯一的 active factory 组织。0 个或多个都明确拒绝——多工厂将来再设计。

    ``organizations`` 表自己也在 C18G 行级隔离之下(owner 的请求上下文被算死在最早
    建的贸易公司),这一处只读查询必须摘掉隔离才看得见工厂组织。
    """
    with without_org_data_isolation():
        rows = list(
            db.scalars(
                select(OrganizationRecord).where(
                    OrganizationRecord.org_type == ORG_TYPE_FACTORY,
                    OrganizationRecord.status == "active",
                )
            )
        )
    if not rows:
        raise FactoryNotConfigured("未配置制造组织(org_type=factory)")
    if len(rows) > 1:
        raise FactoryNotConfigured("存在多个制造组织,多工厂尚未支持")
    org = rows[0]
    return FactoryContext(factory_org_id=org.org_id, org_name=org.org_name)


PERMISSION_READ = "mfg.inventory.read"
PERMISSION_MANAGE = "mfg.inventory.manage"


def user_may_access(
    user: User,
    ctx: FactoryContext,
    db: Session | None = None,
    action: str = "read",
) -> bool:
    """库存的门(2026-09-10 用户拍板放开):

    - owner 全通;制造公司自己的 super_admin 全通(不看权限码,与原规矩一致);
    - 其他人必须**同时**满足:在制造公司有 active 成员关系 + 权限页勾了
      ``mfg.inventory.read``(查)或 ``mfg.inventory.manage``(入库/生产/发货/调整/建档)。
      manage 蕴含 read。
    - 不传 ``db`` 就只能走前两条(没法查成员关系与权限)。
    """
    if is_owner_role(user.role):
        return True
    if is_super_admin_role(user.role):
        return (user.organization_id or "") == ctx.factory_org_id
    if db is None:
        return False
    from ....models.org_membership import OrgMembershipRecord
    from ....services.permission_service import user_has_permission

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
    if user_has_permission(db, user, PERMISSION_MANAGE):
        return True
    return action != "manage" and user_has_permission(db, user, PERMISSION_READ)


# ---------------------------------------------------------------- 小工具


def _commit(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def _actor_name(db: Session, user: User) -> str:
    """单据操作人给人看的名字：C19 显示名（霓旌/白苏婉的汉字）→ 登录名 → id。"""
    return user_display_name(db, user)


def _q(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001"))


def _get_item(db: Session, ctx: FactoryContext, item_id: UUID) -> M.MfgItem:
    item = db.scalar(
        select(M.MfgItem).where(
            M.MfgItem.id == item_id,
            M.MfgItem.factory_org_id == ctx.factory_org_id,
        )
    )
    if item is None:
        raise MfgNotFound("物料/成品不存在")
    return item


def _lock_items(
    db: Session, ctx: FactoryContext, item_ids: list[UUID]
) -> dict[UUID, M.MfgItem]:
    """按 id 顺序锁行,防止两张生产单并发双扣。"""
    ordered = sorted(set(item_ids), key=str)
    rows = db.scalars(
        select(M.MfgItem)
        .where(
            M.MfgItem.id.in_(ordered),
            M.MfgItem.factory_org_id == ctx.factory_org_id,
        )
        .order_by(M.MfgItem.id)
        .with_for_update()
    ).all()
    found = {row.id: row for row in rows}
    missing = [str(i) for i in ordered if i not in found]
    if missing:
        raise MfgNotFound(f"物料/成品不存在: {', '.join(missing)}")
    return found


def stock_of(db: Session, ctx: FactoryContext, item_ids: list[UUID]) -> dict[UUID, Decimal]:
    if not item_ids:
        return {}
    rows = db.execute(
        select(M.MfgMovement.item_id, func.coalesce(func.sum(M.MfgMovement.qty_delta), 0))
        .where(
            M.MfgMovement.factory_org_id == ctx.factory_org_id,
            M.MfgMovement.item_id.in_(list(set(item_ids))),
        )
        .group_by(M.MfgMovement.item_id)
    ).all()
    result = {item_id: ZERO for item_id in item_ids}
    for item_id, total in rows:
        result[item_id] = _q(total)
    return result


def _next_doc_no(db: Session, ctx: FactoryContext, doc_type: str) -> str:
    counter = db.scalar(
        select(M.MfgDocCounter)
        .where(
            M.MfgDocCounter.factory_org_id == ctx.factory_org_id,
            M.MfgDocCounter.doc_type == doc_type,
        )
        .with_for_update()
    )
    if counter is None:
        counter = M.MfgDocCounter(
            factory_org_id=ctx.factory_org_id, doc_type=doc_type, next_no=1
        )
        db.add(counter)
        db.flush()
        # 并发首建可能撞唯一键;重取一次
        counter = db.scalar(
            select(M.MfgDocCounter)
            .where(
                M.MfgDocCounter.factory_org_id == ctx.factory_org_id,
                M.MfgDocCounter.doc_type == doc_type,
            )
            .with_for_update()
        )
        assert counter is not None
    number = counter.next_no
    counter.next_no = number + 1
    return f"{M.DOC_NO_PREFIX[doc_type]}-{number:06d}"


def _new_document(
    db: Session,
    ctx: FactoryContext,
    *,
    user: User,
    doc_type: str,
    note: str | None,
    payload: dict[str, Any],
) -> M.MfgDocument:
    doc = M.MfgDocument(
        factory_org_id=ctx.factory_org_id,
        doc_type=doc_type,
        doc_no=_next_doc_no(db, ctx, doc_type),
        actor_user_id=str(user.id),
        actor_name=_actor_name(db, user),
        note=(note or None),
        payload_json=payload,
    )
    db.add(doc)
    db.flush()
    return doc


def _add_movement(
    db: Session, ctx: FactoryContext, doc: M.MfgDocument, item_id: UUID, delta: Decimal
) -> None:
    db.add(
        M.MfgMovement(
            factory_org_id=ctx.factory_org_id,
            document_id=doc.id,
            item_id=item_id,
            qty_delta=_q(delta),
        )
    )


# ---------------------------------------------------------------- 主档


def list_items(
    db: Session,
    ctx: FactoryContext,
    *,
    kind: str | None = None,
    q: str | None = None,
    include_archived: bool = False,
) -> list[M.MfgItem]:
    stmt = select(M.MfgItem).where(M.MfgItem.factory_org_id == ctx.factory_org_id)
    if kind:
        stmt = stmt.where(M.MfgItem.kind == kind)
    if not include_archived:
        stmt = stmt.where(M.MfgItem.is_archived.is_(False))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(M.MfgItem.code.ilike(like) | M.MfgItem.name.ilike(like))
    return list(db.scalars(stmt.order_by(M.MfgItem.kind, M.MfgItem.code)))


# ---------------------------------------------------------------- 编码组 / 自动编码


def _format_code(kind: str, group_code: str, number: int) -> str:
    return f"{group_code}-{number:0{M.CODE_DIGITS[kind]}d}"


def _code_exists(db: Session, ctx: FactoryContext, code: str) -> bool:
    return (
        db.scalar(
            select(M.MfgItem.id).where(
                M.MfgItem.factory_org_id == ctx.factory_org_id,
                M.MfgItem.code == code,
            )
        )
        is not None
    )


def ensure_default_groups(db: Session, ctx: FactoryContext) -> None:
    """物料大类一次性预置;已有任何物料大类就不动。"""
    existing = db.scalar(
        select(func.count())
        .select_from(M.MfgCodeGroup)
        .where(
            M.MfgCodeGroup.factory_org_id == ctx.factory_org_id,
            M.MfgCodeGroup.kind == M.KIND_PART,
        )
    )
    if existing:
        return
    taken = set(
        db.scalars(
            select(M.MfgCodeGroup.code).where(
                M.MfgCodeGroup.factory_org_id == ctx.factory_org_id
            )
        )
    )
    for code, name in DEFAULT_PART_GROUPS:
        if code in taken:
            continue
        db.add(
            M.MfgCodeGroup(
                factory_org_id=ctx.factory_org_id, kind=M.KIND_PART, code=code, name=name
            )
        )
    _commit(db)


def list_code_groups(
    db: Session, ctx: FactoryContext, *, kind: str | None = None, include_archived: bool = False
) -> list[S.CodeGroupRead]:
    if kind in (None, M.KIND_PART):
        ensure_default_groups(db, ctx)
    stmt = select(M.MfgCodeGroup).where(M.MfgCodeGroup.factory_org_id == ctx.factory_org_id)
    if kind:
        stmt = stmt.where(M.MfgCodeGroup.kind == kind)
    if not include_archived:
        stmt = stmt.where(M.MfgCodeGroup.is_archived.is_(False))
    groups = list(db.scalars(stmt.order_by(M.MfgCodeGroup.kind, M.MfgCodeGroup.code)))
    counts = dict(
        db.execute(
            select(M.MfgItem.group_id, func.count())
            .where(
                M.MfgItem.factory_org_id == ctx.factory_org_id,
                M.MfgItem.group_id.is_not(None),
            )
            .group_by(M.MfgItem.group_id)
        ).all()
    )
    return [
        S.CodeGroupRead(
            id=g.id,
            kind=g.kind,
            code=g.code,
            name=g.name,
            next_no=g.next_no,
            is_archived=g.is_archived,
            item_count=int(counts.get(g.id, 0)),
        )
        for g in groups
    ]


def _get_group(db: Session, ctx: FactoryContext, group_id: UUID, *, lock: bool = False) -> M.MfgCodeGroup:
    stmt = select(M.MfgCodeGroup).where(
        M.MfgCodeGroup.id == group_id,
        M.MfgCodeGroup.factory_org_id == ctx.factory_org_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    group = db.scalar(stmt)
    if group is None:
        raise MfgNotFound("系列/大类不存在")
    return group


def create_code_group(
    db: Session, ctx: FactoryContext, payload: S.CodeGroupCreate
) -> M.MfgCodeGroup:
    dup = db.scalar(
        select(M.MfgCodeGroup).where(
            M.MfgCodeGroup.factory_org_id == ctx.factory_org_id,
            M.MfgCodeGroup.code == payload.code,
        )
    )
    if dup is not None:
        label = "系列" if dup.kind == M.KIND_PRODUCT else "大类"
        raise MfgError(f"组码 {payload.code} 已被{label}「{dup.name}」占用")
    if payload.code in M.DOC_NO_PREFIX.values():
        raise MfgError(f"组码 {payload.code} 是单据号前缀,换一个")
    group = M.MfgCodeGroup(
        factory_org_id=ctx.factory_org_id,
        kind=payload.kind,
        code=payload.code,
        name=payload.name,
    )
    db.add(group)
    _commit(db)
    db.refresh(group)
    return group


def suggest_group_code(db: Session, ctx: FactoryContext, name: str, *, length: int = 3) -> S.CodeSuggestion:
    """按名字给组码建议:英文取词首字母,中文取拼音首字母,截到 ``length`` 位。

    只是建议,人可以改;``taken`` 告诉前端这个建议是否已被占用。
    """
    letters: list[str] = []
    ascii_words = [w for w in "".join(ch if ch.isalnum() else " " for ch in name).split() if w.isascii()]
    if ascii_words:
        letters = [w[0] for w in ascii_words if w[0].isalpha()]
        if len(letters) < 2 and ascii_words:
            letters = [ch for ch in ascii_words[0] if ch.isalpha()]
    else:
        for syllable in lazy_pinyin(name, style=Style.FIRST_LETTER, errors="ignore"):
            if syllable and syllable[0].isalpha():
                letters.append(syllable[0])
    code = "".join(letters).upper()[:length]
    if len(code) < 2:
        code = (code + "XX")[:2]
    taken = (
        db.scalar(
            select(M.MfgCodeGroup.id).where(
                M.MfgCodeGroup.factory_org_id == ctx.factory_org_id,
                M.MfgCodeGroup.code == code,
            )
        )
        is not None
    ) or code in M.DOC_NO_PREFIX.values()
    return S.CodeSuggestion(code=code, taken=taken)


def _first_free_number(db: Session, ctx: FactoryContext, group: M.MfgCodeGroup) -> tuple[int, str]:
    """从 next_no 起找第一个没被占用的号(手填编码可能已经占了 TBL-002)。"""
    number = group.next_no
    while True:
        code = _format_code(group.kind, group.code, number)
        if not _code_exists(db, ctx, code):
            return number, code
        number += 1


def preview_next_code(db: Session, ctx: FactoryContext, group_id: UUID) -> S.NextCodePreview:
    """只算不占号;真正的号在建档事务里 FOR UPDATE 取。"""
    group = _get_group(db, ctx, group_id)
    _, code = _first_free_number(db, ctx, group)
    return S.NextCodePreview(group_id=group.id, code=code)


def _allocate_code(db: Session, ctx: FactoryContext, group_id: UUID, kind: str) -> tuple[M.MfgCodeGroup, str]:
    group = _get_group(db, ctx, group_id, lock=True)
    if group.kind != kind:
        label = "系列" if group.kind == M.KIND_PRODUCT else "大类"
        raise MfgError(f"「{group.name}」是{'成品' if group.kind == M.KIND_PRODUCT else '物料'}{label},和要建的类型对不上")
    if group.is_archived:
        raise MfgError(f"「{group.name}」已归档,不能再发号")
    number, code = _first_free_number(db, ctx, group)
    group.next_no = number + 1
    return group, code


def create_item(
    db: Session, ctx: FactoryContext, payload: S.ItemCreate
) -> M.MfgItem:
    group_id: UUID | None = None
    if payload.group_id is not None:
        group, code = _allocate_code(db, ctx, payload.group_id, payload.kind)
        group_id = group.id
    else:
        assert payload.code is not None
        code = payload.code
        if _code_exists(db, ctx, code):
            raise MfgError(f"编码 {code} 已存在")
    item = M.MfgItem(
        factory_org_id=ctx.factory_org_id,
        kind=payload.kind,
        code=code,
        group_id=group_id,
        name=payload.name,
        unit=payload.unit,
        note=payload.note,
    )
    db.add(item)
    _commit(db)
    db.refresh(item)
    return item


def patch_item(
    db: Session, ctx: FactoryContext, item_id: UUID, patch: S.ItemPatch
) -> M.MfgItem:
    item = _get_item(db, ctx, item_id)
    data = patch.model_dump(exclude_unset=True)
    new_code = data.pop("code", None)
    if new_code is not None and new_code != item.code:
        has_movement = db.scalar(
            select(M.MfgMovement.id).where(M.MfgMovement.item_id == item.id).limit(1)
        )
        if has_movement is not None:
            raise MfgError(f"{item.code} 已有流水,编码不能再改(单据上都印着它)")
        if _code_exists(db, ctx, new_code):
            raise MfgError(f"编码 {new_code} 已存在")
        item.code = new_code
        item.group_id = None  # 手改过的编码不再属于自动发号的组
    for key, value in data.items():
        if isinstance(value, str) and key != "note":
            value = value.strip()
        setattr(item, key, value)
    _commit(db)
    db.refresh(item)
    return item


def stock_rows(
    db: Session, ctx: FactoryContext, *, kind: str | None = None, include_archived: bool = False
) -> list[S.StockRow]:
    items = list_items(db, ctx, kind=kind, include_archived=include_archived)
    stocks = stock_of(db, ctx, [i.id for i in items])
    bom_counts = dict(
        db.execute(
            select(M.MfgBomLine.product_id, func.count())
            .where(M.MfgBomLine.factory_org_id == ctx.factory_org_id)
            .group_by(M.MfgBomLine.product_id)
        ).all()
    )
    return [
        S.StockRow(
            **S.ItemRead.model_validate(item).model_dump(),
            stock=stocks.get(item.id, ZERO),
            bom_line_count=int(bom_counts.get(item.id, 0)),
        )
        for item in items
    ]


# ---------------------------------------------------------------- BOM


def _bom_lines_with_parts(
    db: Session, ctx: FactoryContext, product_id: UUID
) -> list[tuple[M.MfgBomLine, M.MfgItem]]:
    part = aliased(M.MfgItem)
    rows = db.execute(
        select(M.MfgBomLine, part)
        .join(part, part.id == M.MfgBomLine.part_id)
        .where(
            M.MfgBomLine.product_id == product_id,
            M.MfgBomLine.factory_org_id == ctx.factory_org_id,
        )
        .order_by(M.MfgBomLine.position, part.code)
    ).all()
    return [(line, p) for line, p in rows]


def get_bom(db: Session, ctx: FactoryContext, product_id: UUID) -> S.BomRead:
    product = _get_item(db, ctx, product_id)
    if product.kind != M.KIND_PRODUCT:
        raise MfgError("只有成品才有配件清单")
    return S.BomRead(
        product_id=product.id,
        lines=[
            S.BomLineRead(
                id=line.id,
                part_id=part.id,
                part_code=part.code,
                part_name=part.name,
                part_unit=part.unit,
                mode=line.mode,
                qty=line.qty,
                position=line.position,
            )
            for line, part in _bom_lines_with_parts(db, ctx, product.id)
        ],
    )


def replace_bom(
    db: Session, ctx: FactoryContext, product_id: UUID, payload: S.BomReplace
) -> S.BomRead:
    product = _get_item(db, ctx, product_id)
    if product.kind != M.KIND_PRODUCT:
        raise MfgError("只有成品才有配件清单")
    part_ids = [line.part_id for line in payload.lines]
    if part_ids:
        parts = {
            row.id: row
            for row in db.scalars(
                select(M.MfgItem).where(
                    M.MfgItem.id.in_(part_ids),
                    M.MfgItem.factory_org_id == ctx.factory_org_id,
                )
            )
        }
        for pid in part_ids:
            part = parts.get(pid)
            if part is None:
                raise MfgNotFound(f"物料 {pid} 不存在")
            if part.kind != M.KIND_PART:
                raise MfgError(f"{part.code} 是成品,一期不支持成品套成品")
            if part.is_archived:
                raise MfgError(f"{part.code} 已归档,不能再进配件清单")
    for old in db.scalars(
        select(M.MfgBomLine).where(M.MfgBomLine.product_id == product.id)
    ):
        db.delete(old)
    db.flush()
    for position, line in enumerate(payload.lines):
        db.add(
            M.MfgBomLine(
                factory_org_id=ctx.factory_org_id,
                product_id=product.id,
                part_id=line.part_id,
                mode=line.mode,
                qty=_q(line.qty),
                position=position,
            )
        )
    _commit(db)
    return get_bom(db, ctx, product.id)


# ---------------------------------------------------------------- 需求计算


def required_for(mode: str, bom_qty: Decimal, produce_qty: Decimal) -> Decimal:
    """per_unit: 每件消耗 bom_qty;per_carton: 每 bom_qty 件装一箱,向上取整。"""
    if mode == M.BOM_MODE_PER_UNIT:
        return _q(produce_qty * bom_qty)
    cartons = (produce_qty / bom_qty).to_integral_value(rounding=ROUND_CEILING)
    return _q(cartons)


def _requirements(
    db: Session,
    ctx: FactoryContext,
    product: M.MfgItem,
    qty: Decimal,
    *,
    lock: bool,
) -> list[S.RequirementRow]:
    lines = _bom_lines_with_parts(db, ctx, product.id)
    if not lines:
        raise MfgError(f"{product.code} 还没有配件清单,先去成品台填写")
    part_ids = [part.id for _, part in lines]
    if lock:
        _lock_items(db, ctx, part_ids + [product.id])
    stocks = stock_of(db, ctx, part_ids)
    rows: list[S.RequirementRow] = []
    for line, part in lines:
        required = required_for(line.mode, line.qty, qty)
        available = stocks.get(part.id, ZERO)
        short = _q(required - available) if required > available else ZERO
        rows.append(
            S.RequirementRow(
                item_id=part.id,
                code=part.code,
                name=part.name,
                unit=part.unit,
                mode=line.mode,
                bom_qty=line.qty,
                required=required,
                available=available,
                short=short,
            )
        )
    return rows


def preview_production(
    db: Session, ctx: FactoryContext, product_id: UUID, qty: Decimal
) -> S.ProductionPreview:
    product = _get_item(db, ctx, product_id)
    if product.kind != M.KIND_PRODUCT:
        raise MfgError("只能生产成品")
    rows = _requirements(db, ctx, product, _q(qty), lock=False)
    return S.ProductionPreview(
        product_id=product.id,
        qty=_q(qty),
        requirements=rows,
        feasible=all(r.short == ZERO for r in rows),
    )


# ---------------------------------------------------------------- 四个动作


def receipt(
    db: Session, ctx: FactoryContext, *, user: User, payload: S.ReceiptCreate
) -> M.MfgDocument:
    item_ids = [line.item_id for line in payload.lines]
    items = _lock_items(db, ctx, item_ids)
    merged: dict[UUID, Decimal] = {}
    for line in payload.lines:
        merged[line.item_id] = merged.get(line.item_id, ZERO) + _q(line.qty)
    doc = _new_document(
        db,
        ctx,
        user=user,
        doc_type=M.DOC_RECEIPT,
        note=payload.note,
        payload={
            "lines": [
                {
                    "item_id": str(i),
                    "code": items[i].code,
                    "name": items[i].name,
                    "unit": items[i].unit,
                    "qty": str(q),
                }
                for i, q in merged.items()
            ]
        },
    )
    for item_id, qty in merged.items():
        _add_movement(db, ctx, doc, item_id, qty)
    _commit(db)
    db.refresh(doc)
    return doc


def production(
    db: Session, ctx: FactoryContext, *, user: User, payload: S.ProductionCreate
) -> M.MfgDocument:
    product = _get_item(db, ctx, payload.product_id)
    if product.kind != M.KIND_PRODUCT:
        raise MfgError("只能生产成品")
    if product.is_archived:
        raise MfgError(f"{product.code} 已归档")
    qty = _q(payload.qty)
    rows = _requirements(db, ctx, product, qty, lock=True)
    shortages = [r for r in rows if r.short > ZERO]
    if shortages:
        db.rollback()
        names = "、".join(f"{r.name} 缺 {r.short} {r.unit}" for r in shortages)
        raise InsufficientStock(f"物料不足,已拒绝整单:{names}", shortages)
    doc = _new_document(
        db,
        ctx,
        user=user,
        doc_type=M.DOC_PRODUCTION,
        note=payload.note,
        payload={
            "product": {
                "item_id": str(product.id),
                "code": product.code,
                "name": product.name,
                "unit": product.unit,
                "qty": str(qty),
            },
            # 冻结当时的 BOM:明年改了配方,历史单据还能照当时的算法解释
            "bom_snapshot": [
                {
                    "item_id": str(r.item_id),
                    "code": r.code,
                    "name": r.name,
                    "unit": r.unit,
                    "mode": r.mode,
                    "bom_qty": str(r.bom_qty),
                    "consumed": str(r.required),
                }
                for r in rows
            ],
        },
    )
    for r in rows:
        _add_movement(db, ctx, doc, r.item_id, -r.required)
    _add_movement(db, ctx, doc, product.id, qty)
    _commit(db)
    db.refresh(doc)
    return doc


def shipment(
    db: Session, ctx: FactoryContext, *, user: User, payload: S.ShipmentCreate
) -> M.MfgDocument:
    product = _get_item(db, ctx, payload.product_id)
    if product.kind != M.KIND_PRODUCT:
        raise MfgError("只能发货成品")
    qty = _q(payload.qty)
    _lock_items(db, ctx, [product.id])
    available = stock_of(db, ctx, [product.id])[product.id]
    if available < qty:
        db.rollback()
        short = _q(qty - available)
        raise InsufficientStock(
            f"成品不足,已拒绝:{product.name} 现有 {available} {product.unit},缺 {short}",
            [
                S.RequirementRow(
                    item_id=product.id,
                    code=product.code,
                    name=product.name,
                    unit=product.unit,
                    mode=M.BOM_MODE_PER_UNIT,
                    bom_qty=Decimal("1"),
                    required=qty,
                    available=available,
                    short=short,
                )
            ],
        )
    doc = _new_document(
        db,
        ctx,
        user=user,
        doc_type=M.DOC_SHIPMENT,
        note=payload.note,
        payload={
            "product": {
                "item_id": str(product.id),
                "code": product.code,
                "name": product.name,
                "unit": product.unit,
                "qty": str(qty),
            }
        },
    )
    _add_movement(db, ctx, doc, product.id, -qty)
    _commit(db)
    db.refresh(doc)
    return doc


def adjustment(
    db: Session, ctx: FactoryContext, *, user: User, payload: S.AdjustmentCreate
) -> M.MfgDocument:
    item = _get_item(db, ctx, payload.item_id)
    delta = _q(payload.qty_delta)
    _lock_items(db, ctx, [item.id])
    available = stock_of(db, ctx, [item.id])[item.id]
    if available + delta < ZERO:
        db.rollback()
        raise InsufficientStock(
            f"调整后会变成负数:{item.name} 现有 {available} {item.unit},调整 {delta}",
            [
                S.RequirementRow(
                    item_id=item.id,
                    code=item.code,
                    name=item.name,
                    unit=item.unit,
                    mode=M.BOM_MODE_PER_UNIT,
                    bom_qty=Decimal("1"),
                    required=-delta,
                    available=available,
                    short=_q(-delta - available),
                )
            ],
        )
    doc = _new_document(
        db,
        ctx,
        user=user,
        doc_type=M.DOC_ADJUSTMENT,
        note=payload.reason,
        payload={
            "item": {
                "item_id": str(item.id),
                "code": item.code,
                "name": item.name,
                "unit": item.unit,
            },
            "qty_delta": str(delta),
            "before": str(available),
            "after": str(_q(available + delta)),
            "reason": payload.reason,
        },
    )
    _add_movement(db, ctx, doc, item.id, delta)
    _commit(db)
    db.refresh(doc)
    return doc


# ---------------------------------------------------------------- 查账


def _movement_reads(
    db: Session, ctx: FactoryContext, *, where: list[Any], limit: int, offset: int
) -> tuple[list[S.MovementRead], int]:
    base = (
        select(M.MfgMovement, M.MfgDocument, M.MfgItem)
        .join(M.MfgDocument, M.MfgDocument.id == M.MfgMovement.document_id)
        .join(M.MfgItem, M.MfgItem.id == M.MfgMovement.item_id)
        .where(M.MfgMovement.factory_org_id == ctx.factory_org_id, *where)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        base.order_by(M.MfgMovement.created_at.desc(), M.MfgMovement.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return (
        [
            S.MovementRead(
                id=mv.id,
                document_id=doc.id,
                doc_no=doc.doc_no,
                doc_type=doc.doc_type,
                item_id=item.id,
                item_code=item.code,
                item_name=item.name,
                item_unit=item.unit,
                qty_delta=mv.qty_delta,
                created_at=mv.created_at,
            )
            for mv, doc, item in rows
        ],
        int(total),
    )


def item_movements(
    db: Session, ctx: FactoryContext, item_id: UUID, *, limit: int, offset: int
) -> tuple[list[S.MovementRead], int]:
    _get_item(db, ctx, item_id)
    return _movement_reads(
        db, ctx, where=[M.MfgMovement.item_id == item_id], limit=limit, offset=offset
    )


def list_documents(
    db: Session,
    ctx: FactoryContext,
    *,
    doc_type: str | None,
    item_id: UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[M.MfgDocument], int]:
    stmt = select(M.MfgDocument).where(
        M.MfgDocument.factory_org_id == ctx.factory_org_id
    )
    if doc_type:
        stmt = stmt.where(M.MfgDocument.doc_type == doc_type)
    if item_id is not None:
        stmt = stmt.where(
            M.MfgDocument.id.in_(
                select(M.MfgMovement.document_id).where(
                    M.MfgMovement.item_id == item_id,
                    M.MfgMovement.factory_org_id == ctx.factory_org_id,
                )
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(M.MfgDocument.created_at.desc(), M.MfgDocument.doc_no.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, int(total)


def get_document(
    db: Session, ctx: FactoryContext, document_id: UUID
) -> tuple[M.MfgDocument, list[S.MovementRead]]:
    doc = db.scalar(
        select(M.MfgDocument).where(
            M.MfgDocument.id == document_id,
            M.MfgDocument.factory_org_id == ctx.factory_org_id,
        )
    )
    if doc is None:
        raise MfgNotFound("单据不存在")
    movements, _ = _movement_reads(
        db, ctx, where=[M.MfgMovement.document_id == doc.id], limit=1000, offset=0
    )
    return doc, movements
