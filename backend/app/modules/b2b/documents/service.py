"""开单据。**内容整份快照,发出去就不再随源数据变。**"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import policies
from ..wholesale.models import B2BWholesaleItem
from . import banking, sample_credits
from .models import (
    DOC_STATUS_DRAFT,
    DOC_STATUS_ISSUED,
    DOC_TYPE_COMMERCIAL,
    DOC_TYPE_PACKING,
    DOC_TYPE_PROFORMA,
    STAGE_QUOTED,
    STAGES,
    B2BDocument,
)


class DocumentError(RuntimeError):
    """人能看懂的错误,直接冒到界面上。"""


_NUMBER_PREFIX = {
    DOC_TYPE_PROFORMA: "PI",
    DOC_TYPE_COMMERCIAL: "CI",
    DOC_TYPE_PACKING: "PL",
}


def _next_number(db: Session, issued_on: date, doc_type: str = DOC_TYPE_PROFORMA) -> str:
    """`PI-20260730-001`。带日期是为了人一眼看出新旧;序号在当天内递增。

    **不用全局自增**:单号会印在买家的汇款附言里,连续的全局序号等于把
    "我们一共开过几单"告诉每一个客户。
    """
    prefix = f"{_NUMBER_PREFIX.get(doc_type, 'DOC')}-{issued_on:%Y%m%d}-"
    used = db.scalar(
        select(func.count())
        .select_from(B2BDocument)
        .where(B2BDocument.number.like(f"{prefix}%"))
    )
    return f"{prefix}{int(used or 0) + 1:03d}"


def _line(item: B2BWholesaleItem, qty: int) -> dict[str, object]:
    price = Decimal(str(item.wholesale_price or "0"))
    # 阶梯价:数量够了自动用更低那档。**买家不该靠自己发现优惠**,
    # 而且手动挑档位迟早挑错,印错价的单子是要认的。
    for tier in sorted(
        (
            (int(t.get("min_qty") or 0), Decimal(str(t.get("unit_price"))))
            for t in (item.price_tiers_json or [])
            if isinstance(t, dict) and t.get("min_qty") and t.get("unit_price")
        ),
    ):
        if qty >= tier[0]:
            price = tier[1]
    # 箱规和箱数一起冻进快照:装箱单是从 PI 派生的,那时候再去查批发目录,
    # 箱规万一改过就和买家手上那张对不上——清关按装箱单核对实物。
    case_pack = int(item.case_pack or 0) or None
    cartons = -(-qty // case_pack) if case_pack else None
    return {
        "sku": item.sku,
        "name": item.product_name,
        "variant": item.variant_note or "",
        "qty": qty,
        "case_pack": case_pack,
        "cartons": cartons,
        "unit_price": str(price),
        "line_total": str((price * qty).quantize(Decimal("0.01"))),
    }


def create_proforma(
    db: Session,
    *,
    buyer_company: str,
    lines: list[dict],
    buyer_contact: str | None = None,
    buyer_email: str | None = None,
    buyer_address: str | None = None,
    ship_to: str | None = None,
    freight: Decimal | None = None,
    notes: str | None = None,
) -> B2BDocument:
    company = str(buyer_company or "").strip()
    if not company:
        raise DocumentError("买方公司名必填。")

    profile = banking.read(db)
    missing = banking.missing_required(profile)
    if missing:
        # 没有收款信息的 PI 是废纸:买家拿到只会回来问钱汇哪儿。
        raise DocumentError(
            "开单前先在「收款信息」里填全：" + "、".join(missing)
        )

    wanted = {str(entry.get("item_id")): int(entry.get("qty") or 0) for entry in lines}
    wanted = {k: v for k, v in wanted.items() if v > 0}
    if not wanted:
        raise DocumentError("至少要有一个产品，而且数量大于 0。")

    rows = {
        str(row.id): row
        for row in db.scalars(
            select(B2BWholesaleItem).where(
                B2BWholesaleItem.id.in_([UUID(k) for k in wanted])
            )
        )
    }
    missing_items = [k for k in wanted if k not in rows]
    if missing_items:
        raise DocumentError("有产品不在批发目录里，刷新一下再试。")

    unpriced = [rows[k].sku for k in wanted if not rows[k].wholesale_price]
    if unpriced:
        raise DocumentError(
            "这些产品还没填批发价，开不了单：" + "、".join(sorted(unpriced))
        )

    items = [_line(rows[k], qty) for k, qty in wanted.items()]
    items.sort(key=lambda entry: str(entry["sku"]))
    subtotal = sum(Decimal(str(entry["line_total"])) for entry in items)
    freight_value = Decimal(str(freight)) if freight is not None else None
    total = subtotal + (freight_value or Decimal("0"))

    issued_on = datetime.now(UTC).date()
    document = B2BDocument(
        doc_type=DOC_TYPE_PROFORMA,
        number=_next_number(db, issued_on, DOC_TYPE_PROFORMA),
        stage=STAGE_QUOTED,
        status=DOC_STATUS_DRAFT,
        issued_on=issued_on,
        valid_until=issued_on + timedelta(days=policies.QUOTE_VALID_DAYS),
        buyer_company=company[:200],
        buyer_contact=(buyer_contact or None),
        buyer_email=(buyer_email or None),
        buyer_address=(buyer_address or None),
        ship_to=(ship_to or None),
        items_json=items,
        # **条款和收款信息一起快照**:改 policies.py 或换银行都不该动已开的单。
        terms_json={
            "legal_entity": policies.LEGAL_ENTITY,
            "address_lines": list(policies.ADDRESS_LINES),
            "contact_email": policies.B2B_CONTACT_EMAIL,
            "contact_phone": policies.CONTACT_PHONE,
            "payment_terms": policies.PAYMENT_TERMS,
            "delivery_line": policies.DELIVERY_LINE,
            "lead_time_note": "Lead time starts once payment has cleared.",
            "country_of_origin": "China",
            "banking": dict(profile),
        },
        currency=policies.DEFAULT_CURRENCY,
        subtotal=subtotal.quantize(Decimal("0.01")),
        freight=freight_value,
        total=total.quantize(Decimal("0.01")),
        notes=(notes or None),
    )
    db.add(document)
    db.flush()

    # 样品费抵扣。**开单时自动扣,不靠人记**——这句话我们已经在小窗、批发页、
    # 图册、开发信四处承诺过,靠脑子记到第三个客户就开始虚。
    # 抵扣封顶在货款(subtotal),不抵运费:运费是货代实付,抵掉等于我们贴钱。
    credit = sample_credits.consume(
        db,
        buyer_email=buyer_email,
        document_id=document.id,
        cap=document.subtotal,
    )
    if credit:
        document.sample_credit = credit
        document.total = (document.total - credit).quantize(Decimal("0.01"))
        db.flush()
    return document


def create_shipping_document(
    db: Session, *, source_id: UUID, doc_type: str, carton_count: int | None = None,
    gross_weight_kg: Decimal | None = None, net_weight_kg: Decimal | None = None,
) -> B2BDocument:
    """从一张 PI 派生商业发票或装箱单。

    **行项目原样继承那张 PI**,不重新从批发目录取:报关金额必须和买家实付
    一致,重新取会在中途调价时对不上——那是海关最不能容忍的一种不一致。
    """
    if doc_type not in (DOC_TYPE_COMMERCIAL, DOC_TYPE_PACKING):
        raise DocumentError("只能派生商业发票或装箱单。")
    source = db.get(B2BDocument, source_id)
    if source is None or source.doc_type != DOC_TYPE_PROFORMA:
        raise DocumentError("要先有一张形式发票，才能出这两张。")

    issued_on = datetime.now(UTC).date()
    document = B2BDocument(
        doc_type=doc_type,
        number=_next_number(db, issued_on, doc_type),
        status=DOC_STATUS_DRAFT,
        stage=source.stage,
        source_document_id=source.id,
        issued_on=issued_on,
        # 这两张不是报价,没有"过期"一说;沿用源单日期只是为了列不为空。
        valid_until=source.valid_until,
        buyer_company=source.buyer_company,
        buyer_contact=source.buyer_contact,
        buyer_email=source.buyer_email,
        buyer_address=source.buyer_address,
        ship_to=source.ship_to,
        items_json=list(source.items_json or []),
        terms_json=dict(source.terms_json or {}),
        currency=source.currency,
        subtotal=source.subtotal,
        freight=source.freight,
        sample_credit=source.sample_credit,
        total=source.total,
        carton_count=carton_count if carton_count and carton_count > 0 else None,
        gross_weight_kg=gross_weight_kg,
        net_weight_kg=net_weight_kg,
        notes=source.notes,
    )
    db.add(document)
    db.flush()
    return document


def set_stage(db: Session, *, document_id: UUID, stage: str) -> B2BDocument:
    """推进订单阶段。开完 PI 之后此前是没有下文的——定金到没到、在不在生产、
    发货没发货,全靠脑子记。"""
    if stage not in STAGES:
        raise DocumentError("未知的订单阶段。")
    row = db.get(B2BDocument, document_id)
    if row is None:
        raise DocumentError("单据不存在。")
    if row.doc_type != DOC_TYPE_PROFORMA:
        raise DocumentError("只有形式发票才有订单阶段。")
    row.stage = stage
    db.flush()
    return row


def mark_issued(db: Session, *, document_id: UUID) -> B2BDocument:
    row = db.get(B2BDocument, document_id)
    if row is None:
        raise DocumentError("单据不存在。")
    row.status = DOC_STATUS_ISSUED
    db.flush()
    return row


def listing(db: Session, *, limit: int = 100) -> list[B2BDocument]:
    return list(
        db.scalars(
            select(B2BDocument)
            .order_by(B2BDocument.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    )
