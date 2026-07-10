"""Notification inbox API + the n8n / P-pipeline ingest webhook."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from ...api.deps import get_current_user
from ...db.session import get_db
from ...models.user import User
from . import service
from .schemas import (
    MarkReadResponse,
    NotificationIngest,
    NotificationListResponse,
    NotificationRead,
    UnreadCountResponse,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])

INGEST_TOKEN_ENV = "P_NOTIFICATIONS_INGEST_TOKEN"


def _ingest_token() -> str | None:
    value = os.getenv(INGEST_TOKEN_ENV, "").strip()
    return value or None


@router.get("", response_model=NotificationListResponse)
def list_notifications_endpoint(
    status: str | None = Query(default=None),
    level: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NotificationListResponse:
    rows, total, unread = service.list_notifications(
        db,
        status=status,
        level=level,
        limit=limit,
        offset=offset,
        user_id=str(user.id),
    )
    return NotificationListResponse(
        items=[NotificationRead.model_validate(row) for row in rows],
        count=total,
        unread=unread,
        limit=limit,
        offset=offset,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
def unread_count_endpoint(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UnreadCountResponse:
    return UnreadCountResponse(
        unread=service.unread_count(db, user_id=str(user.id))
    )


@router.post("/{notification_id}/read", response_model=MarkReadResponse)
def mark_read_endpoint(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MarkReadResponse:
    updated = service.mark_read(db, notification_id, user_id=str(user.id))
    db.commit()
    return MarkReadResponse(updated=updated)


@router.post("/read-all", response_model=MarkReadResponse)
def mark_all_read_endpoint(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MarkReadResponse:
    updated = service.mark_all_read(db, user_id=str(user.id))
    db.commit()
    return MarkReadResponse(updated=updated)


@router.post("/ingest", response_model=NotificationRead, status_code=201)
def ingest_endpoint(
    payload: NotificationIngest,
    db: Session = Depends(get_db),
    x_notify_token: str | None = Header(default=None),
) -> NotificationRead:
    """Server-to-server: n8n / the P upload pipeline records a result here.

    Secured by a shared secret (``P_NOTIFICATIONS_INGEST_TOKEN``). Until that
    env var is set the endpoint is closed, so notifications cannot be spoofed.
    In-console emitters call ``service.create_notification`` directly and do
    not go through this webhook.
    """
    expected = _ingest_token()
    if expected is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Ingest webhook is disabled: set "
                f"{INGEST_TOKEN_ENV} on the backend to enable n8n callbacks."
            ),
        )
    if x_notify_token != expected:
        raise HTTPException(status_code=401, detail="Invalid ingest token.")
    row = service.create_notification(
        db,
        event_type=payload.event_type,
        title=payload.title,
        body=payload.body,
        level=payload.level,
        source=payload.source,
        org_id=payload.org_id,
        product_id=payload.product_id,
        external_refs=payload.external_refs,
        payload=payload.payload,
    )
    db.commit()
    db.refresh(row)
    return NotificationRead.model_validate(row)
