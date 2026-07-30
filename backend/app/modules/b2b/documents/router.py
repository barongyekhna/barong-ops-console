"""单据 API:开 PI、列清单、下载 PDF、填收款信息。"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ....db.session import get_db
from ....models.user import User
from ..wholesale.router import (
    PERMISSION_MANAGE,
    PERMISSION_READ,
    _require_b2b_permission,
)
from . import banking, sample_credits, service
from .models import B2BDocument
from .render_pdf import render_pdf

router = APIRouter(prefix="/b2b", tags=["b2b-documents"])


class DocumentLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: UUID
    qty: int = Field(gt=0)


class DocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    buyer_company: str = Field(min_length=1, max_length=200)
    buyer_contact: str | None = Field(default=None, max_length=120)
    buyer_email: str | None = Field(default=None, max_length=320)
    buyer_address: str | None = None
    ship_to: str | None = None
    lines: list[DocumentLine] = Field(min_length=1)
    freight: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    number: str
    doc_type: str
    doc_type_label: str = ""
    stage: str = "quoted"
    stage_label: str = ""
    status: str
    issued_on: str
    valid_until: str
    buyer_company: str
    buyer_email: str | None = None
    currency: str
    subtotal: Decimal
    freight: Decimal | None = None
    sample_credit: Decimal | None = None
    total: Decimal
    item_count: int = 0
    source_document_id: UUID | None = None


def _to_read(row: B2BDocument) -> DocumentRead:
    from .models import DOC_TYPE_LABELS, STAGE_LABELS

    return DocumentRead(
        id=row.id,
        number=row.number,
        doc_type=row.doc_type,
        doc_type_label=DOC_TYPE_LABELS.get(row.doc_type, row.doc_type),
        stage=row.stage,
        stage_label=STAGE_LABELS.get(row.stage, row.stage),
        status=row.status,
        issued_on=f"{row.issued_on:%Y-%m-%d}",
        valid_until=f"{row.valid_until:%Y-%m-%d}",
        buyer_company=row.buyer_company,
        buyer_email=row.buyer_email,
        currency=row.currency,
        subtotal=row.subtotal,
        freight=row.freight,
        sample_credit=row.sample_credit,
        total=row.total,
        source_document_id=row.source_document_id,
        item_count=len(row.items_json or []),
    )


class BankingProfileIO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beneficiary: str = ""
    bank_name: str = ""
    swift: str = ""
    account: str = ""
    bank_address: str = ""
    intermediary: str = ""


@router.get("/banking")
def read_banking(
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> dict[str, object]:
    profile = banking.read(db)
    return {
        "profile": profile,
        "missing_required": banking.missing_required(profile),
        "fields": [
            {"key": key, "label": label, "required": required}
            for key, label, required in banking.FIELDS
        ],
    }


@router.put("/banking")
def write_banking(
    payload: BankingProfileIO,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> dict[str, object]:
    profile = banking.write(db, payload.model_dump())
    db.commit()
    return {
        "profile": profile,
        "missing_required": banking.missing_required(profile),
    }


@router.get("/documents", response_model=list[DocumentRead])
def list_documents(
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> list[DocumentRead]:
    return [_to_read(row) for row in service.listing(db)]


@router.post("/documents", response_model=DocumentRead)
def create_document(
    payload: DocumentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> DocumentRead:
    try:
        row = service.create_proforma(
            db,
            buyer_company=payload.buyer_company,
            buyer_contact=payload.buyer_contact,
            buyer_email=payload.buyer_email,
            buyer_address=payload.buyer_address,
            ship_to=payload.ship_to,
            lines=[entry.model_dump() for entry in payload.lines],
            freight=payload.freight,
            notes=payload.notes,
        )
    except service.DocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    db.commit()
    db.refresh(row)
    return _to_read(row)


@router.get("/documents/{document_id}/pdf")
def download_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> Response:
    row = db.get(B2BDocument, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="单据不存在。")
    return Response(
        content=render_pdf(row),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{row.number}.pdf"'
        },
    )


# --------------------------------------------------------------------------
# 样品抵扣台账 / 发货单据 / 订单阶段
# --------------------------------------------------------------------------


class SampleCreditCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    buyer_email: str = Field(min_length=3, max_length=320)
    amount: Decimal = Field(gt=0)
    buyer_company: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)


class SampleCreditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    buyer_email: str
    buyer_company: str | None = None
    amount: Decimal
    currency: str
    paid_on: str
    note: str | None = None
    consumed: bool = False


@router.get("/sample-credits", response_model=list[SampleCreditRead])
def list_sample_credits(
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> list[SampleCreditRead]:
    return [
        SampleCreditRead(
            id=row.id,
            buyer_email=row.buyer_email,
            buyer_company=row.buyer_company,
            amount=row.amount,
            currency=row.currency,
            paid_on=f"{row.paid_on:%Y-%m-%d}",
            note=row.note,
            consumed=row.consumed_document_id is not None,
        )
        for row in sample_credits.listing(db)
    ]


@router.post("/sample-credits", response_model=SampleCreditRead)
def add_sample_credit(
    payload: SampleCreditCreate,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> SampleCreditRead:
    """记一笔已付的样品费。开 PI 时自动抵扣,不用人记。"""
    row = sample_credits.record(
        db,
        buyer_email=payload.buyer_email,
        amount=payload.amount,
        buyer_company=payload.buyer_company,
        note=payload.note,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="邮箱或金额不对。",
        )
    db.commit()
    db.refresh(row)
    return SampleCreditRead(
        id=row.id,
        buyer_email=row.buyer_email,
        buyer_company=row.buyer_company,
        amount=row.amount,
        currency=row.currency,
        paid_on=f"{row.paid_on:%Y-%m-%d}",
        note=row.note,
        consumed=False,
    )


class ShippingDocCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_type: str
    carton_count: int | None = Field(default=None, gt=0)
    gross_weight_kg: Decimal | None = Field(default=None, gt=0)
    net_weight_kg: Decimal | None = Field(default=None, gt=0)


@router.post("/documents/{document_id}/shipping", response_model=DocumentRead)
def create_shipping_doc(
    document_id: UUID,
    payload: ShippingDocCreate,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> DocumentRead:
    """从一张 PI 派生商业发票或装箱单。发货报关要这两张。"""
    try:
        row = service.create_shipping_document(
            db,
            source_id=document_id,
            doc_type=payload.doc_type,
            carton_count=payload.carton_count,
            gross_weight_kg=payload.gross_weight_kg,
            net_weight_kg=payload.net_weight_kg,
        )
    except service.DocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    db.commit()
    db.refresh(row)
    return _to_read(row)


class StagePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str


@router.patch("/documents/{document_id}/stage", response_model=DocumentRead)
def set_document_stage(
    document_id: UUID,
    payload: StagePatch,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> DocumentRead:
    try:
        row = service.set_stage(db, document_id=document_id, stage=payload.stage)
    except service.DocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    db.commit()
    db.refresh(row)
    return _to_read(row)
