"""Webhook 登记簿 API（模块控制页「Webhook」标签的数据源）。

只做记录备查，不参与真实调用链 —— 各系列的 webhook 调用仍走各自配置
（如 P 系列 env ``N8N_P_UPLOAD_WEBHOOK``）。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, DateTime, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from ...api.deps import get_current_user
from ...db.base import Base
from ...db.session import get_db
from ...models.user import User

router = APIRouter(prefix="/webhook-registry", tags=["webhook-registry"])


class WebhookRegistryEntry(Base):
    __tablename__ = "webhook_registry_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    series: Mapped[str] = mapped_column(String(32), nullable=False)
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    webhook_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    respond_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class WebhookEntryRead(BaseModel):
    id: int
    series: str
    workflow_name: str
    webhook_url: str
    respond_url: str | None = None
    notes: str | None = None


class WebhookEntryCreate(BaseModel):
    series: str = Field(min_length=1, max_length=32)
    workflow_name: str = Field(min_length=1, max_length=255)
    webhook_url: str = Field(min_length=1, max_length=1024)
    respond_url: str | None = Field(default=None, max_length=1024)
    notes: str | None = None


class WebhookEntryListResponse(BaseModel):
    entries: list[WebhookEntryRead]


@router.get("", response_model=WebhookEntryListResponse)
def list_webhook_entries(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WebhookEntryListResponse:
    del user
    rows = db.scalars(
        select(WebhookRegistryEntry).order_by(
            WebhookRegistryEntry.series.asc(),
            WebhookRegistryEntry.workflow_name.asc(),
        )
    ).all()
    return WebhookEntryListResponse(
        entries=[WebhookEntryRead.model_validate(row, from_attributes=True) for row in rows]
    )


@router.post("", response_model=WebhookEntryRead, status_code=201)
def create_webhook_entry(
    payload: WebhookEntryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WebhookEntryRead:
    del user
    row = WebhookRegistryEntry(
        series=payload.series.strip().upper(),
        workflow_name=payload.workflow_name.strip(),
        webhook_url=payload.webhook_url.strip(),
        respond_url=(payload.respond_url or "").strip() or None,
        notes=payload.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return WebhookEntryRead.model_validate(row, from_attributes=True)


@router.delete("/{entry_id}", status_code=204)
def delete_webhook_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 注意：这里不能写 -> None 返回注解——线上 FastAPI 版本会把它当响应模型，
    # 和 204 冲突直接断言崩溃（2026-07-11 生产事故）。
    del user
    row = db.get(WebhookRegistryEntry, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="登记不存在。")
    db.delete(row)
    db.commit()
