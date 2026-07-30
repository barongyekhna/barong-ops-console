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
from . import banking, service
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
    status: str
    issued_on: str
    valid_until: str
    buyer_company: str
    buyer_email: str | None = None
    currency: str
    subtotal: Decimal
    freight: Decimal | None = None
    total: Decimal
    item_count: int = 0


def _to_read(row: B2BDocument) -> DocumentRead:
    return DocumentRead(
        id=row.id,
        number=row.number,
        status=row.status,
        issued_on=f"{row.issued_on:%Y-%m-%d}",
        valid_until=f"{row.valid_until:%Y-%m-%d}",
        buyer_company=row.buyer_company,
        buyer_email=row.buyer_email,
        currency=row.currency,
        subtotal=row.subtotal,
        freight=row.freight,
        total=row.total,
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
