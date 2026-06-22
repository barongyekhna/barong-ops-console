import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.db.session import SessionLocal
from backend.app.models.artifact import Artifact
from backend.app.models.error import SystemError
from backend.app.models.job import AutomationJob, JobEvent
from backend.app.models.memory import MemoryEvent
from backend.app.models.operation_log import OperationLog
from backend.app.models.registry import (
    AgentRegistry,
    ModuleRegistry,
    WorkflowRegistry,
)
from backend.app.models.review import ReviewItem

pytestmark = pytest.mark.integration

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ORG_ID = "org_11111111111111111111111111111111"
EXPECTED_EVENTS = [
    "created",
    "running",
    "artifact_created",
    "review_requested",
    "memory_event_created",
    "completed_demo",
]


def _foundation_failure_debug() -> str:
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(SystemError)
                .where(SystemError.error_code == "FOUNDATION_DEMO_RUN_FAILED")
                .order_by(SystemError.id.desc())
                .limit(3)
            )
        )
        payload = [
            {
                "error_code": row.error_code,
                "message": row.message,
                "details": row.details,
            }
            for row in rows
        ]
    return json.dumps(payload, default=str, sort_keys=True)


def test_foundation_demo_run_requires_owner_token(
    auth_client: TestClient,
) -> None:
    response = auth_client.post("/api/control-plane/foundation-demo/run")

    assert response.status_code == 401


def test_disabled_foundation_demo_blocks_execution(
    owner_client: TestClient,
) -> None:
    disabled = owner_client.patch(
        "/api/control-plane/module-control/organizations/"
        f"{DEFAULT_ORG_ID}/registry-entries/experimental.foundation_demo",
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text

    response = owner_client.post("/api/control-plane/foundation-demo/run")

    assert response.status_code == 403
    assert response.headers["x-barong-error-code"] == "MODULE_DISABLED"
    assert response.json()["detail"]["code"] == "MODULE_DISABLED"
    with SessionLocal() as db:
        job_count = db.scalar(
            select(func.count()).select_from(AutomationJob).where(
                AutomationJob.module_id == "foundation_demo"
            )
        )

    assert job_count == 0
    restored = owner_client.patch(
        "/api/control-plane/module-control/organizations/"
        f"{DEFAULT_ORG_ID}/registry-entries/experimental.foundation_demo",
        json={"enabled": True},
    )
    assert restored.status_code == 200, restored.text


def test_owner_runs_complete_safe_foundation_demo(
    owner_client: TestClient,
) -> None:
    response = owner_client.post("/api/control-plane/foundation-demo/run")

    assert response.status_code == 201, _foundation_failure_debug()
    payload = response.json()
    assert payload["module"]["module_key"] == "foundation_demo"
    assert payload["agent"]["agent_key"] == "foundation_demo_agent"
    assert (
        payload["workflow"]["workflow_key"]
        == "foundation_demo_workflow"
    )
    assert payload["workflow"]["trigger_type"] == "internal_demo"
    assert payload["job"]["job_type"] == "foundation_demo"
    assert payload["job"]["status"] == "completed_demo"
    assert payload["job"]["input_payload"]["real_business_task"] is False
    assert [item["event_type"] for item in payload["job_events"]] == (
        EXPECTED_EVENTS
    )
    assert payload["events_count"] == len(EXPECTED_EVENTS)
    assert payload["artifact"]["artifact_type"] == "demo_report"
    assert payload["artifact"]["title"] == "Foundation Demo Report"
    assert payload["review"]["status"] == "pending_demo"
    assert payload["review"]["decision"] is None
    assert (
        payload["memory_event"]["event_type"]
        == "foundation_demo_completed"
    )
    assert "demo exercise" in payload["memory_event"]["summary"].lower()
    assert payload["operation_log_count"] >= 11

    job_id = payload["job"]["job_id"]
    with SessionLocal() as db:
        job = db.scalar(
            select(AutomationJob).where(AutomationJob.job_id == job_id)
        )
        events = list(
            db.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job_id)
                .order_by(JobEvent.id)
            )
        )
        artifact = db.scalar(
            select(Artifact).where(Artifact.job_id == job_id)
        )
        review = db.scalar(
            select(ReviewItem).where(ReviewItem.job_id == job_id)
        )
        memory_event = db.scalar(
            select(MemoryEvent).where(MemoryEvent.job_id == job_id)
        )
        operation_logs = list(
            db.scalars(
                select(OperationLog)
                .where(OperationLog.job_id == job_id)
                .order_by(OperationLog.id)
            )
        )
        job_snapshot = (
            None
            if job is None
            else {
                "status": job.status,
                "started": job.started_at is not None,
                "finished": job.finished_at is not None,
            }
        )
        event_types = [event.event_type for event in events]
        artifact_snapshot = (
            None
            if artifact is None
            else {
                "storage_provider": artifact.storage_provider,
                "storage_ref": artifact.storage_ref,
                "metadata": dict(artifact.artifact_metadata or {}),
            }
        )
        review_snapshot = (
            None
            if review is None
            else {"status": review.status, "decision": review.decision}
        )
        memory_snapshot = (
            None
            if memory_event is None
            else {"payload": dict(memory_event.payload or {})}
        )
        operation_log_count = len(operation_logs)
        log_details = {
            operation_log.action: dict(operation_log.details or {})
            for operation_log in operation_logs
        }

    assert job_snapshot is not None
    assert job_snapshot["status"] == "completed_demo"
    assert job_snapshot["started"] is True
    assert job_snapshot["finished"] is True
    assert event_types == EXPECTED_EVENTS
    assert artifact_snapshot is not None
    assert artifact_snapshot["storage_provider"] == "demo_metadata"
    assert artifact_snapshot["storage_ref"].startswith("demo/internal/foundation/")
    assert not any(
        marker in artifact_snapshot["storage_ref"].lower()
        for marker in ("http://", "https://", "s3://", "minio", "filebrowser")
    )
    assert artifact_snapshot["metadata"]["file_uploaded"] is False
    assert review_snapshot is not None
    assert review_snapshot["status"] == "pending_demo"
    assert review_snapshot["decision"] is None
    assert memory_snapshot is not None
    assert memory_snapshot["payload"]["model_called"] is False
    assert operation_log_count == payload["operation_log_count"]
    assert log_details["foundation_demo.review_created"][
        "downstream_triggered"
    ] is False
    assert log_details["foundation_demo.memory_event_created"][
        "model_called"
    ] is False
    assert log_details["foundation_demo.run_completed"][
        "workflow_triggered"
    ] is False


def test_latest_returns_most_recent_foundation_demo(
    owner_client: TestClient,
) -> None:
    first = owner_client.post("/api/control-plane/foundation-demo/run")
    second = owner_client.post("/api/control-plane/foundation-demo/run")

    assert first.status_code == 201, _foundation_failure_debug()
    assert second.status_code == 201, _foundation_failure_debug()
    latest = owner_client.get("/api/control-plane/foundation-demo/latest")

    assert latest.status_code == 200
    payload = latest.json()
    assert payload["job"]["job_id"] == second.json()["job"]["job_id"]
    assert payload["job"]["job_id"] != first.json()["job"]["job_id"]
    assert payload["job"]["status"] == "completed_demo"
    assert payload["events_count"] == len(EXPECTED_EVENTS)
    assert payload["artifact"]["title"] == "Foundation Demo Report"
    assert payload["review"]["status"] == "pending_demo"
    assert payload["memory_event"]["summary"]

    with SessionLocal() as db:
        module_count = db.scalar(
            select(func.count()).select_from(ModuleRegistry).where(
                ModuleRegistry.module_id == "foundation_demo"
            )
        )
        agent_count = db.scalar(
            select(func.count()).select_from(AgentRegistry).where(
                AgentRegistry.agent_id == "foundation_demo_agent"
            )
        )
        workflow_count = db.scalar(
            select(func.count()).select_from(WorkflowRegistry).where(
                WorkflowRegistry.workflow_id == "foundation_demo_workflow"
            )
        )
        job_count = db.scalar(
            select(func.count()).select_from(AutomationJob).where(
                AutomationJob.module_id == "foundation_demo"
            )
        )

    assert module_count == 1
    assert agent_count == 1
    assert workflow_count == 1
    assert job_count == 2


def test_foundation_demo_responses_exclude_credentials(
    owner_client: TestClient,
) -> None:
    run = owner_client.post("/api/control-plane/foundation-demo/run")
    latest = owner_client.get("/api/control-plane/foundation-demo/latest")

    assert run.status_code == 201, _foundation_failure_debug()
    assert latest.status_code == 200
    serialized = json.dumps(
        {"run": run.json(), "latest": latest.json()},
        sort_keys=True,
    ).lower()
    for marker in (
        "password_hash",
        '"token"',
        '"secret"',
        '"api_key"',
        "private_key",
        "authorization",
    ):
        assert marker not in serialized


def test_failed_foundation_demo_rolls_back_and_records_failure(
    owner_client: TestClient,
    monkeypatch,
) -> None:
    def fail_artifact_creation(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("controlled demo test failure")

    monkeypatch.setattr(
        "backend.app.services.foundation_demo_service.create_artifact",
        fail_artifact_creation,
    )

    response = owner_client.post("/api/control-plane/foundation-demo/run")

    assert response.status_code == 500
    with SessionLocal() as db:
        demo_job_count = db.scalar(
            select(func.count()).select_from(AutomationJob).where(
                AutomationJob.module_id == "foundation_demo"
            )
        )
        system_error = db.scalar(
            select(SystemError).where(
                SystemError.error_code == "FOUNDATION_DEMO_RUN_FAILED"
            )
        )
        failure_log = db.scalar(
            select(OperationLog).where(
                OperationLog.action == "foundation_demo.run",
                OperationLog.result == "failure",
            )
        )
        system_error_details = (
            None if system_error is None else dict(system_error.details or {})
        )
        failure_log_details = (
            None if failure_log is None else dict(failure_log.details or {})
        )

    assert demo_job_count == 0
    assert system_error_details is not None
    assert system_error_details["real_business_effect"] is False
    assert failure_log_details is not None
    assert failure_log_details["transaction_rolled_back"] is True
    assert failure_log_details["external_http_called"] is False


def test_foundation_demo_runtime_has_no_external_clients_or_model_calls() -> None:
    inspected_paths = (
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "api"
        / "routes"
        / "foundation_demo.py",
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "repositories"
        / "foundation_demo.py",
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "services"
        / "foundation_demo_service.py",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in inspected_paths
    ).lower()

    for marker in (
        "import httpx",
        "import requests",
        "urllib.request",
        "aiohttp",
        "deepseek",
        "webhook",
    ):
        assert marker not in source
