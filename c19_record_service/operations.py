"""Content-free operational snapshot for the private Record Service."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from .models import (
    ChatRecord,
    Moment,
    MomentComment,
    MomentLike,
    MomentAssetReference,
    MomentUserEvent,
    RecordIdempotencyLedger,
    RecordAssetDeletionOutbox,
    RecordAssetReference,
    RecordMutationAudit,
    UserRecordEvent,
)
from .schemas import RecordOpsSnapshot


MOMENT_STATES = ("draft", "published", "delete_pending", "deleted")


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return max(0, int((now - value.astimezone(UTC)).total_seconds()))


def record_ops_snapshot(session: Session) -> RecordOpsSnapshot:
    """Return bounded aggregate state; never select a body or identifier."""

    now = datetime.now(UTC)
    state_rows = session.execute(
        select(Moment.state, func.count(Moment.id)).group_by(Moment.state)
    ).all()
    states = {state: 0 for state in MOMENT_STATES}
    for state, count in state_rows:
        if state in states:
            states[state] = int(count)
    oldest_draft = session.scalar(
        select(func.min(Moment.created_at)).where(Moment.state == "draft")
    )
    oldest_delete_pending = session.scalar(
        select(func.min(Moment.delete_pending_at)).where(
            Moment.state == "delete_pending"
        )
    )
    has_chat_reference = exists().where(
        RecordAssetReference.asset_id == RecordAssetDeletionOutbox.asset_id
    )
    has_moment_reference = exists().where(
        MomentAssetReference.asset_id == RecordAssetDeletionOutbox.asset_id
    )
    asset_deletion_pending = int(
        session.scalar(
            select(func.count(RecordAssetDeletionOutbox.id)).where(
                RecordAssetDeletionOutbox.state == "pending"
            )
        )
        or 0
    )
    asset_deletion_blocked = int(
        session.scalar(
            select(func.count(RecordAssetDeletionOutbox.id)).where(
                RecordAssetDeletionOutbox.state == "pending",
                or_(has_chat_reference, has_moment_reference),
            )
        )
        or 0
    )
    asset_deletion_leased = int(
        session.scalar(
            select(func.count(RecordAssetDeletionOutbox.id)).where(
                RecordAssetDeletionOutbox.state.in_(("pending", "authorized")),
                RecordAssetDeletionOutbox.lease_until > now,
            )
        )
        or 0
    )
    oldest_asset_deletion_pending = session.scalar(
        select(func.min(RecordAssetDeletionOutbox.created_at)).where(
            RecordAssetDeletionOutbox.state == "pending"
        )
    )
    oldest_asset_deletion_authorized = session.scalar(
        select(func.min(RecordAssetDeletionOutbox.authorized_at)).where(
            RecordAssetDeletionOutbox.state == "authorized"
        )
    )
    return RecordOpsSnapshot(
        status="ok",
        service="c19-record-service",
        generated_at=now,
        chat_records=int(session.scalar(select(func.count(ChatRecord.id))) or 0),
        chat_delivery_events=int(
            session.scalar(select(func.count(UserRecordEvent.id))) or 0
        ),
        idempotency_tombstones=int(
            session.scalar(
                select(func.count(RecordIdempotencyLedger.client_message_id)).where(
                    RecordIdempotencyLedger.status == "deleted"
                )
            )
            or 0
        ),
        mutation_audits=int(
            session.scalar(select(func.count(RecordMutationAudit.id))) or 0
        ),
        asset_deletion_pending=asset_deletion_pending,
        asset_deletion_authorized=int(
            session.scalar(
                select(func.count(RecordAssetDeletionOutbox.id)).where(
                    RecordAssetDeletionOutbox.state == "authorized"
                )
            )
            or 0
        ),
        asset_deletion_blocked=asset_deletion_blocked,
        asset_deletion_leased=asset_deletion_leased,
        asset_deletion_completed=int(
            session.scalar(
                select(func.count(RecordAssetDeletionOutbox.id)).where(
                    RecordAssetDeletionOutbox.state == "completed"
                )
            )
            or 0
        ),
        asset_deletion_protected=int(
            session.scalar(
                select(func.count(RecordAssetDeletionOutbox.id)).where(
                    RecordAssetDeletionOutbox.state == "protected"
                )
            )
            or 0
        ),
        oldest_asset_deletion_pending_age_seconds=_age_seconds(
            now, oldest_asset_deletion_pending
        ),
        oldest_asset_deletion_authorized_age_seconds=_age_seconds(
            now, oldest_asset_deletion_authorized
        ),
        moment_states=states,
        moment_likes=int(session.scalar(select(func.count(MomentLike.moment_id))) or 0),
        active_moment_comments=int(
            session.scalar(
                select(func.count(MomentComment.id)).where(
                    MomentComment.status == "active"
                )
            )
            or 0
        ),
        moment_events=int(
            session.scalar(select(func.count(MomentUserEvent.id))) or 0
        ),
        oldest_draft_age_seconds=_age_seconds(now, oldest_draft),
        oldest_delete_pending_age_seconds=_age_seconds(
            now, oldest_delete_pending
        ),
    )


__all__ = ["record_ops_snapshot"]
