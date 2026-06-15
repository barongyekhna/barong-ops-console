import json
from pathlib import Path

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

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_EVENTS = [
    "created",
    "running",
    "artifact_created",
    "review_requested",
    "memory_event_created",
    "completed_demo",
]


def test_foundation_demo_run_requires_owner_token(
    auth_client: TestClient,
) -> None:
    response = auth_client.post("/api/control-plane/foundation-demo/run")

    assert response.status_code == 401


def test_owner_runs_complete_safe_foundation_demo(
    owner_client: TestClient,
) -> None:
    response = owner_client.post("/api/control-plane/foundation-demo/run")

    assert response.status_code == 201
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

    assert job is not None
    assert job.status == "completed_demo"
    assert job.started_at is not None
    assert job.finished_at is not None
    assert [event.event_type for event in events] == EXPECTED_EVENTS
    assert artifact is not None
    assert artifact.storage_provider == "demo_metadata"
    assert artifact.storage_ref.startswith("demo/internal/foundation/")
    assert not any(
        marker in artifact.storage_ref.lower()
        for marker in ("http://", "https://", "s3://", "minio", "filebrowser")
    )
    assert artifact.artifact_metadata["file_uploaded"] is False
    assert review is not None
    assert review.status == "pending_demo"
    assert review.decision is None
    assert memory_event is not None
    assert memory_event.payload["model_called"] is False
    assert len(operation_logs) == payload["operation_log_count"]

    log_details = {
        operation_log.action: operation_log.details
        for operation_log in operation_logs
    }
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

    assert first.status_code == 201
    assert second.status_code == 201
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

    assert run.status_code == 201
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

    assert demo_job_count == 0
    assert system_error is not None
    assert system_error.details["real_business_effect"] is False
    assert failure_log is not None
    assert failure_log.details["transaction_rolled_back"] is True
    assert failure_log.details["external_http_called"] is False


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
