from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models.job import AutomationJob, JobEvent
from backend.app.models.operation_log import OperationLog
from tests.backend.foundation_helpers import create_job, create_module


def test_create_demo_job_without_real_completion(
    owner_client: TestClient,
) -> None:
    create_module(owner_client)

    created = owner_client.post(
        "/jobs",
        json={
            "job_id": "demo.job",
            "module_key": "demo.module",
            "status": "pending",
            "input_payload": {"kind": "foundation"},
        },
    )
    blocked_completed = owner_client.post(
        "/jobs",
        json={
            "job_id": "demo.completed-job",
            "module_key": "demo.module",
            "status": "completed",
        },
    )

    assert created.status_code == 201
    assert created.json()["status"] == "pending"
    assert blocked_completed.status_code == 422

    with SessionLocal() as db:
        log = db.scalar(
            select(OperationLog).where(
                OperationLog.action == "job.create_demo"
            )
        )
    assert log is not None
    assert log.details["execution"] == "not_triggered"


def test_job_events_append_and_update_only_safe_demo_status(
    owner_client: TestClient,
) -> None:
    create_module(owner_client)
    create_job(owner_client)

    note = owner_client.post(
        "/jobs/demo.job/events",
        json={"event_type": "note", "details": {"message": "demo only"}},
    )
    status_change = owner_client.post(
        "/jobs/demo.job/events",
        json={"event_type": "status_change", "to_status": "completed_demo"},
    )
    blocked_status = owner_client.post(
        "/jobs/demo.job/events",
        json={"event_type": "status_change", "to_status": "completed"},
    )

    assert note.status_code == 201
    assert status_change.status_code == 201
    assert status_change.json()["from_status"] == "pending"
    assert status_change.json()["to_status"] == "completed_demo"
    assert blocked_status.status_code == 422

    events = owner_client.get("/jobs/demo.job/events")
    assert events.status_code == 200
    assert [item["event_type"] for item in events.json()["items"]] == [
        "note",
        "status_change",
    ]

    with SessionLocal() as db:
        job = db.scalar(
            select(AutomationJob).where(
                AutomationJob.job_id == "demo.job"
            )
        )
        stored_events = list(
            db.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == "demo.job")
                .order_by(JobEvent.id)
            )
        )
    assert job is not None
    assert job.status == "completed_demo"
    assert len(stored_events) == 2
