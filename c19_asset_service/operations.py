"""Content-free operational snapshot for the private Asset Service."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from .models import ASSET_STATES, ASSET_USAGES, Asset, AssetAuditEvent, TransferTicket
from .quota import reserved_asset_bytes_expression, retained_asset_predicate
from .schemas import AssetOpsSnapshot


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return max(0, int((now - value.astimezone(UTC)).total_seconds()))


def asset_ops_snapshot(
    session: Session, dataset_id: str, thumbnail_max_bytes: int
) -> AssetOpsSnapshot:
    """Return lifecycle counts and queue ages without selecting object metadata."""

    now = datetime.now(UTC)
    state_rows = session.execute(
        select(Asset.status, func.count(Asset.asset_id)).group_by(Asset.status)
    ).all()
    states = {state: 0 for state in ASSET_STATES}
    for state, count in state_rows:
        if state in states:
            states[state] = int(count)
    usage_rows = session.execute(
        select(Asset.usage, func.count(Asset.asset_id)).group_by(Asset.usage)
    ).all()
    usages = {usage: 0 for usage in ASSET_USAGES}
    for usage, count in usage_rows:
        if usage in usages:
            usages[usage] = int(count)
    oldest_by_state: dict[str, int | None] = {}
    for state in ("pending_upload", "uploaded", "scanning", "delete_pending"):
        oldest = session.scalar(
            select(func.min(Asset.updated_at)).where(Asset.status == state)
        )
        oldest_by_state[state] = _age_seconds(now, oldest)
    active_tickets = session.scalar(
        select(func.count(TransferTicket.ticket_id)).where(
            TransferTicket.revoked_at.is_(None),
            TransferTicket.expires_at >= now,
            TransferTicket.used_count < TransferTicket.max_uses,
        )
    )
    expired_tickets = session.scalar(
        select(func.count(TransferTicket.ticket_id)).where(
            TransferTicket.expires_at < now
        )
    )
    active_bytes = session.scalar(
        select(
            func.coalesce(
                func.sum(
                    Asset.actual_size_bytes
                    + func.coalesce(Asset.thumbnail_size_bytes, 0)
                ),
                0,
            )
        ).where(
            and_(Asset.status == "active", Asset.actual_size_bytes.is_not(None))
        )
    )
    retained = retained_asset_predicate()
    reserved_files = int(
        session.scalar(select(func.count(Asset.asset_id)).where(retained)) or 0
    )
    reserved_bytes = int(
        session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        reserved_asset_bytes_expression(thumbnail_max_bytes)
                    ),
                    0,
                )
            ).where(retained)
        )
        or 0
    )
    retention_prepared_count = int(
        session.scalar(
            select(func.count(Asset.asset_id)).where(
                Asset.retention_operation_id.is_not(None),
                Asset.status.not_in(("delete_pending", "deleted")),
            )
        )
        or 0
    )
    oldest_retention_prepared = session.scalar(
        select(func.min(Asset.retention_prepared_at)).where(
            Asset.retention_operation_id.is_not(None),
            Asset.status.not_in(("delete_pending", "deleted")),
        )
    )
    return AssetOpsSnapshot(
        status="ok",
        service="c19-asset-service",
        dataset_id=dataset_id,
        generated_at=now,
        asset_states=states,
        asset_usages=usages,
        active_object_bytes=int(active_bytes or 0),
        reserved_asset_files=reserved_files,
        reserved_asset_bytes=reserved_bytes,
        active_transfer_tickets=int(active_tickets or 0),
        expired_transfer_tickets=int(expired_tickets or 0),
        audit_events=int(
            session.scalar(select(func.count(AssetAuditEvent.event_id))) or 0
        ),
        retention_prepared_count=retention_prepared_count,
        oldest_retention_prepared_age_seconds=_age_seconds(
            now, oldest_retention_prepared
        ),
        oldest_pending_upload_age_seconds=oldest_by_state["pending_upload"],
        oldest_uploaded_age_seconds=oldest_by_state["uploaded"],
        oldest_scanning_age_seconds=oldest_by_state["scanning"],
        oldest_delete_pending_age_seconds=oldest_by_state["delete_pending"],
    )


__all__ = ["asset_ops_snapshot"]
