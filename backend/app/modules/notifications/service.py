"""Data-access helpers for notifications. Kept import-light so other modules
(K / I / future P) can call ``create_notification`` directly in-process."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .models import PNotification


def create_notification(
    db: Session,
    *,
    event_type: str,
    title: str,
    body: str | None = None,
    level: str = "info",
    source: str = "system",
    org_id: str | None = None,
    product_id: UUID | None = None,
    external_refs: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> PNotification:
    row = PNotification(
        event_type=event_type,
        title=title,
        body=body,
        level=level,
        source=source,
        org_id=org_id,
        product_id=product_id,
        external_refs=external_refs,
        payload=payload,
        status="unread",
    )
    db.add(row)
    db.flush()
    return row


def unread_count(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(PNotification)
            .where(PNotification.status == "unread")
        )
        or 0
    )


def list_notifications(
    db: Session,
    *,
    status: str | None = None,
    level: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PNotification], int, int]:
    stmt = select(PNotification)
    if status:
        stmt = stmt.where(PNotification.status == status)
    if level:
        stmt = stmt.where(PNotification.level == level)
    total = int(
        db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    )
    ordered = stmt.order_by(
        PNotification.created_at.desc(), PNotification.id.desc()
    )
    rows = list(db.scalars(ordered.limit(limit).offset(offset)))
    return rows, total, unread_count(db)


def mark_read(db: Session, notification_id: int) -> int:
    result = db.execute(
        update(PNotification)
        .where(
            PNotification.id == notification_id,
            PNotification.status == "unread",
        )
        .values(status="read", read_at=datetime.now(UTC))
    )
    return int(result.rowcount or 0)


def mark_all_read(db: Session) -> int:
    result = db.execute(
        update(PNotification)
        .where(PNotification.status == "unread")
        .values(status="read", read_at=datetime.now(UTC))
    )
    return int(result.rowcount or 0)
