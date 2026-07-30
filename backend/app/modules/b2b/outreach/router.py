"""FastAPI endpoints for B2B outreach (templates + draft box)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ....db.session import get_db
from ....models.user import User
from ..wholesale.router import (
    PERMISSION_MANAGE,
    PERMISSION_READ,
    _require_b2b_permission,
)
from . import service
from . import templates_catalog as catalog

router = APIRouter(prefix="/b2b", tags=["b2b-outreach"])


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    kind_label: str = ""
    language: str
    store_type: str = ""
    subject: str
    body: str
    is_builtin: bool = False
    active: bool = True


class TemplatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(default=None, max_length=255)
    body: str | None = None
    active: bool | None = None


class DraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prospect_id: UUID
    kind: str
    language: str
    to_email: str | None = None
    subject: str
    body: str
    status: str
    store_name: str = ""


class DraftPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(default=None, max_length=255)
    body: str | None = None
    status: str | None = Field(default=None, max_length=16)


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=catalog.KIND_FIRST_TOUCH, max_length=32)
    limit: int = Field(default=25, ge=1, le=100)


class BackfillEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=25, ge=1, le=100)
    only_fit: bool = True


def _bad(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
    )


@router.get("/email-templates", response_model=list[TemplateRead])
def list_templates(
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> list[TemplateRead]:
    from sqlalchemy import select

    from .models import B2BEmailTemplate

    rows = list(
        db.scalars(
            select(B2BEmailTemplate).order_by(
                B2BEmailTemplate.kind, B2BEmailTemplate.language
            )
        )
    )
    out = []
    for row in rows:
        item = TemplateRead.model_validate(row)
        item.kind_label = catalog.KIND_LABELS.get(row.kind, row.kind)
        out.append(item)
    return out


@router.post("/email-templates/seed")
def seed_templates(
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> dict[str, int]:
    return {"added": service.seed_templates(db)}


@router.patch("/email-templates/{template_id}", response_model=TemplateRead)
def patch_template(
    template_id: UUID,
    payload: TemplatePatch,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> TemplateRead:
    try:
        row = service.save_template(
            db,
            template_id=template_id,
            subject=payload.subject,
            body=payload.body,
            active=payload.active,
        )
    except service.OutreachError as error:
        raise _bad(error) from error
    item = TemplateRead.model_validate(row)
    item.kind_label = catalog.KIND_LABELS.get(row.kind, row.kind)
    return item


@router.post("/prospect-emails/backfill")
def backfill_emails(
    payload: BackfillEmailRequest,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> dict[str, object]:
    """抓官网联系页补邮箱。免费,不消耗任何额度。"""
    return service.backfill_emails(
        db, limit=payload.limit, only_fit=payload.only_fit
    )


@router.get("/email-drafts", response_model=list[DraftRead])
def list_drafts(
    draft_status: str | None = Query(default="draft", alias="status"),
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_READ)),
) -> list[DraftRead]:
    from ..prospects.models import B2BProspect

    rows = service.list_drafts(db, status=draft_status)
    out = []
    for row in rows:
        item = DraftRead.model_validate(row)
        prospect = db.get(B2BProspect, row.prospect_id)
        item.store_name = prospect.store_name if prospect else ""
        out.append(item)
    return out


@router.post("/email-drafts/generate")
def generate_drafts(
    payload: GenerateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> dict[str, object]:
    """生成草稿。**只生成,永不发送**——发送动作永远在用户手上。"""
    return service.generate_drafts(db, kind=payload.kind, limit=payload.limit)


@router.patch("/email-drafts/{draft_id}", response_model=DraftRead)
def patch_draft(
    draft_id: UUID,
    payload: DraftPatch,
    db: Session = Depends(get_db),
    _: User = Depends(_require_b2b_permission(PERMISSION_MANAGE)),
) -> DraftRead:
    try:
        row = service.update_draft(
            db,
            draft_id=draft_id,
            subject=payload.subject,
            body=payload.body,
            status=payload.status,
        )
    except service.OutreachError as error:
        raise _bad(error) from error
    return DraftRead.model_validate(row)
