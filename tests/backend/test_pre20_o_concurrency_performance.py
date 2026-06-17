from __future__ import annotations

from sqlalchemy import func, select

from backend.app.db.session import SessionLocal
from backend.app.models.observability import EventStreamRecord
from backend.app.models.operation_log import OperationLog
from backend.app.models.organization import OrganizationRecord
from backend.app.repositories.operation_logs import (
    create_operation_log,
    list_operation_logs,
)
from backend.app.services.data_isolation import (
    OrgDataIsolationUserContext,
    org_data_isolation_context,
)
from backend.app.services.event_collector import (
    clear_event_buffer,
    emit_event,
    get_event_emitter_stats,
)

ORG_ID = "org_22222222222222222222222222222222"


def _context() -> OrgDataIsolationUserContext:
    return OrgDataIsolationUserContext(
        org_id=ORG_ID,
        user_id="pre20-user",
        role="owner",
        source="pre20_o_test",
        strict=True,
    )


def test_pre20_o_event_flood_is_durable_and_backed_by_event_streams(
    clean_auth_tables: None,
) -> None:
    clear_event_buffer()

    for index in range(150):
        emitted = emit_event(
            event_type="pre20.event_flood",
            module="C17",
            action="pre20.event_flood",
            source="backend",
            status="success",
            context_id=f"ctx-pre20-flood-{index}",
            org_id="platform",
            payload={
                "index": index,
                "job_id": f"job-pre20-{index % 5}",
                "actor_id": "actor-pre20",
            },
        )
        assert emitted.persisted is True

    with SessionLocal() as db:
        count = db.scalar(
            select(func.count())
            .select_from(EventStreamRecord)
            .where(EventStreamRecord.event_type == "pre20.event_flood")
        )

    stats = get_event_emitter_stats()
    assert count == 150
    assert stats["buffered"] >= 150


def test_pre20_o_high_query_load_uses_cursor_pagination(
    clean_auth_tables: None,
) -> None:
    with SessionLocal() as db:
        db.add(
            OrganizationRecord(
                org_id=ORG_ID,
                org_name="PRE20 Test Org",
                org_type="store",
                owner_user_id="pre20-user",
                status="active",
                metadata_json={},
            )
        )
        db.commit()

    with SessionLocal() as db, org_data_isolation_context(_context()):
        for index in range(120):
            create_operation_log(
                db,
                actor_type="user",
                actor_id=f"actor-{index % 4}",
                action="pre20.high_query",
                target_type="test",
                target_id=f"target-{index}",
                result="success" if index % 2 else "failed",
                job_id=None,
                request_id=f"trace-pre20-{index % 8}",
            )
        db.commit()

    with SessionLocal() as db, org_data_isolation_context(_context()):
        first_page = list_operation_logs(db, limit=25, cursor=None)
        next_cursor = str(first_page[-1].id)
        second_page = list_operation_logs(db, limit=25, cursor=next_cursor)

    assert len(first_page) == 25
    assert len(second_page) == 25
    assert {row.operation_id for row in first_page}.isdisjoint(
        {row.operation_id for row in second_page}
    )
    assert first_page[-1].id > second_page[0].id

    with SessionLocal() as db:
        total = db.scalar(
            select(func.count())
            .select_from(OperationLog)
            .where(OperationLog.org_id == ORG_ID)
        )
    assert total == 120
