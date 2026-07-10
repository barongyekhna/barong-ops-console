"""Data-access helpers for notifications. Kept import-light so other modules
(K / I / future P) can call ``create_notification`` directly in-process."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ...services.data_isolation import without_org_data_isolation
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
    recipient_user_id: str | None = None,
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
        recipient_user_id=recipient_user_id,
        product_id=product_id,
        external_refs=external_refs,
        payload=payload,
        status="unread",
    )
    db.add(row)
    db.flush()
    return row


def _visible_to_user(user_id: str):
    return or_(
        PNotification.recipient_user_id.is_(None),
        PNotification.recipient_user_id == user_id,
    )


def unread_count(db: Session, *, user_id: str) -> int:
    with without_org_data_isolation():
        return int(
            db.scalar(
                select(func.count())
                .select_from(PNotification)
                .where(
                    PNotification.status == "unread",
                    _visible_to_user(user_id),
                )
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
    user_id: str,
) -> tuple[list[PNotification], int, int]:
    stmt = select(PNotification).where(_visible_to_user(user_id))
    if status:
        stmt = stmt.where(PNotification.status == status)
    if level:
        stmt = stmt.where(PNotification.level == level)
    with without_org_data_isolation():
        total = int(
            db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        )
        ordered = stmt.order_by(
            PNotification.created_at.desc(), PNotification.id.desc()
        )
        rows = list(db.scalars(ordered.limit(limit).offset(offset)))
    return rows, total, unread_count(db, user_id=user_id)


def mark_read(db: Session, notification_id: int, *, user_id: str) -> int:
    with without_org_data_isolation():
        result = db.execute(
            update(PNotification)
            .where(
                PNotification.id == notification_id,
                PNotification.status == "unread",
                _visible_to_user(user_id),
            )
            .values(status="read", read_at=datetime.now(UTC))
        )
    return int(result.rowcount or 0)


def mark_all_read(db: Session, *, user_id: str) -> int:
    with without_org_data_isolation():
        result = db.execute(
            update(PNotification)
            .where(
                PNotification.status == "unread",
                _visible_to_user(user_id),
            )
            .values(status="read", read_at=datetime.now(UTC))
        )
    return int(result.rowcount or 0)
