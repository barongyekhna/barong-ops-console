import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.session import SessionLocal
from backend.app.main import app
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
TEST_WEBHOOK_URL = (
    "https://n8n-test.example.invalid/webhook-test/barong-demo"
)
TEST_CALLBACK_SECRET = "f12-example-callback-value-not-for-production"
CALLBACK_PAYLOAD = {
    "run_type": "n8n_test_bridge",
    "test_mode": True,
    "status": "completed_demo",
}


@pytest.fixture(autouse=True)
def block_unmocked_webhook(monkeypatch):
    def blocked_webhook(**kwargs):
        del kwargs
        raise AssertionError("An unmocked n8n test HTTP request was attempted.")

    monkeypatch.setattr(
        "backend.app.services.n8n_test_service.send_n8n_test_webhook",
        blocked_webhook,
    )


def configure_test_bridge(settings: Settings) -> None:
    settings.n8n_test_webhook_url = TEST_WEBHOOK_URL
    settings.n8n_test_callback_secret = SecretStr(TEST_CALLBACK_SECRET)
    settings.n8n_test_request_timeout_seconds = 7


def install_successful_webhook(
    monkeypatch,
    captured: dict[str, Any],
) -> None:
    def fake_webhook(**kwargs):
        captured.update(kwargs)
        return 202

    monkeypatch.setattr(
        "backend.app.services.n8n_test_service.send_n8n_test_webhook",
        fake_webhook,
    )


def create_waiting_test_job(
    owner_client: TestClient,
    test_settings: Settings,
    monkeypatch,
    captured: dict[str, Any] | None = None,
) -> dict[str, Any]:
    configure_test_bridge(test_settings)
    outbound = captured if captured is not None else {}
    install_successful_webhook(monkeypatch, outbound)
    response = owner_client.post("/n8n-test/run")
    assert response.status_code == 201, response.text
    return response.json()


def test_n8n_test_run_requires_owner_token(
    auth_client: TestClient,
) -> None:
    response = auth_client.post("/n8n-test/run")

    assert response.status_code == 401


def test_owner_can_access_latest_n8n_test(
    owner_client: TestClient,
) -> None:
    response = owner_client.get("/n8n-test/latest")

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "No n8n test bridge run has been recorded."
    )


def test_unconfigured_webhook_fails_without_external_request_and_logs(
    owner_client: TestClient,
) -> None:
    response = owner_client.post("/n8n-test/run")

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
    assert "no external request" in response.json()["detail"]

    with SessionLocal() as db:
        job_count = db.scalar(
            select(func.count()).select_from(AutomationJob).where(
                AutomationJob.module_id == "n8n_test_bridge"
            )
        )
        failure_log = db.scalar(
            select(OperationLog).where(
                OperationLog.action == "n8n_test.run",
                OperationLog.result == "failure",
            )
        )

    assert job_count == 0
    assert failure_log is not None
    assert failure_log.error_code == "N8N_TEST_CONFIGURATION_UNAVAILABLE"
    assert failure_log.details["external_http_attempted"] is False


def test_configured_run_creates_test_registry_job_and_safe_payload(
    owner_client: TestClient,
    test_settings: Settings,
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}
    payload = create_waiting_test_job(
        owner_client,
        test_settings,
        monkeypatch,
        captured,
    )

    assert captured["url"] == TEST_WEBHOOK_URL
    assert captured["timeout_seconds"] == 7
    outbound = captured["payload"]
    assert set(outbound) == {
        "job_id",
        "callback_url",
        "callback_secret",
        "test_mode",
        "source",
        "run_type",
    }
    assert outbound["job_id"] == payload["job"]["job_id"]
    assert outbound["callback_url"].endswith("/n8n-test/callback")
    assert outbound["callback_secret"] == TEST_CALLBACK_SECRET
    assert outbound["test_mode"] is True
    assert outbound["source"] == "barong_ops_console"
    assert outbound["run_type"] == "n8n_test_bridge"
    serialized_outbound = json.dumps(outbound).lower()
    for marker in (
        "product_id",
        "product_name",
        "woocommerce",
        "p_series",
        "minio",
        "filebrowser",
    ):
        assert marker not in serialized_outbound

    assert payload["test_mode"] is True
    assert payload["job"]["run_type"] == "n8n_test_bridge"
    assert payload["job"]["status"] == "waiting_callback"
    assert payload["latest_event"]["event_type"] == "webhook_dispatched"
    assert payload["artifact"] is None
    assert payload["review"] is None
    assert payload["memory_event"] is None
    assert payload["error"] is None

    with SessionLocal() as db:
        module = db.scalar(
            select(ModuleRegistry).where(
                ModuleRegistry.module_id == "n8n_test_bridge"
            )
        )
        agent = db.scalar(
            select(AgentRegistry).where(
                AgentRegistry.agent_id == "n8n_test_agent"
            )
        )
        workflow = db.scalar(
            select(WorkflowRegistry).where(
                WorkflowRegistry.workflow_id
                == "n8n_test_webhook_workflow"
            )
        )
        job = db.scalar(
            select(AutomationJob).where(
                AutomationJob.job_id == payload["job"]["job_id"]
            )
        )

    assert module is not None and module.status == "demo"
    assert agent is not None and agent.status == "demo"
    assert workflow is not None and workflow.status == "demo"
    assert workflow.endpoint_ref.startswith("demo://")
    assert TEST_WEBHOOK_URL not in workflow.endpoint_ref
    assert job is not None and job.status == "waiting_callback"
    assert job.input_payload["real_business_task"] is False


@pytest.mark.parametrize("provided_secret", [None, "wrong-test-value"])
def test_callback_rejects_missing_or_wrong_secret_without_leaking_it(
    owner_client: TestClient,
    test_settings: Settings,
    monkeypatch,
    provided_secret: str | None,
) -> None:
    run = create_waiting_test_job(
        owner_client,
        test_settings,
        monkeypatch,
    )
    callback = {
        **CALLBACK_PAYLOAD,
        "job_id": run["job"]["job_id"],
    }
    headers = (
        {}
        if provided_secret is None
        else {"X-Barong-Callback-Secret": provided_secret}
    )

    response = owner_client.post(
        "/n8n-test/callback",
        json=callback,
        headers=headers,
    )

    assert response.status_code == 401
    serialized_response = response.text.lower()
    assert TEST_CALLBACK_SECRET.lower() not in serialized_response
    if provided_secret is not None:
        assert provided_secret not in serialized_response

    with SessionLocal() as db:
        job = db.scalar(
            select(AutomationJob).where(
                AutomationJob.job_id == run["job"]["job_id"]
            )
        )
        failure_log = db.scalar(
            select(OperationLog)
            .where(
                OperationLog.action == "n8n_test.callback",
                OperationLog.result == "failure",
            )
            .order_by(OperationLog.id.desc())
        )

    assert job is not None and job.status == "waiting_callback"
    assert failure_log is not None
    serialized_log = json.dumps(failure_log.details).lower()
    assert TEST_CALLBACK_SECRET.lower() not in serialized_log
    if provided_secret is not None:
        assert provided_secret not in serialized_log
    assert "secret" not in serialized_log
    assert "token" not in serialized_log


def test_authorized_callback_completes_demo_records_and_latest(
    owner_client: TestClient,
    test_settings: Settings,
    monkeypatch,
) -> None:
    run = create_waiting_test_job(
        owner_client,
        test_settings,
        monkeypatch,
    )
    job_id = run["job"]["job_id"]

    response = owner_client.post(
        "/n8n-test/callback",
        json={**CALLBACK_PAYLOAD, "job_id": job_id},
        headers={"X-Barong-Callback-Secret": TEST_CALLBACK_SECRET},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["test_mode"] is True
    assert payload["job"]["status"] == "completed_demo"
    assert payload["latest_event"]["event_type"] == "completed_demo"
    assert payload["artifact"]["artifact_type"] == (
        "n8n_test_callback_report"
    )
    assert payload["artifact"]["title"] == "n8n Test Callback Report"
    assert payload["review"]["status"] == "pending_demo"
    assert payload["memory_event"]["event_type"] == (
        "n8n_test_callback_completed"
    )
    assert "demo mode" in payload["memory_event"]["summary"]
    assert payload["error"] is None

    latest = owner_client.get("/n8n-test/latest")
    assert latest.status_code == 200
    assert latest.json()["job"]["job_id"] == job_id
    assert latest.json()["job"]["status"] == "completed_demo"

    serialized_responses = json.dumps(
        {"callback": payload, "latest": latest.json()}
    ).lower()
    assert TEST_CALLBACK_SECRET.lower() not in serialized_responses
    assert '"callback_secret"' not in serialized_responses
    assert '"callback_token"' not in serialized_responses

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
                select(OperationLog).where(OperationLog.job_id == job_id)
            )
        )

    assert job is not None and job.status == "completed_demo"
    assert job.finished_at is not None
    assert events[-1].to_status == "completed_demo"
    assert artifact is not None
    assert artifact.storage_provider == "demo_metadata"
    assert artifact.artifact_metadata["external_storage"] is False
    assert review is not None and review.status == "pending_demo"
    assert memory_event is not None
    assert memory_event.created_by_type == "test_webhook"
    serialized_logs = json.dumps(
        [operation_log.details for operation_log in operation_logs]
    ).lower()
    assert TEST_CALLBACK_SECRET.lower() not in serialized_logs
    assert "secret" not in serialized_logs
    assert "token" not in serialized_logs


@pytest.mark.parametrize("status_value", ["completed", "success", "production"])
def test_callback_accepts_only_demo_terminal_statuses(
    owner_client: TestClient,
    test_settings: Settings,
    monkeypatch,
    status_value: str,
) -> None:
    run = create_waiting_test_job(
        owner_client,
        test_settings,
        monkeypatch,
    )

    response = owner_client.post(
        "/n8n-test/callback",
        json={
            **CALLBACK_PAYLOAD,
            "job_id": run["job"]["job_id"],
            "status": status_value,
        },
        headers={"X-Barong-Callback-Secret": TEST_CALLBACK_SECRET},
    )

    assert response.status_code == 422


def test_failed_callback_uses_failed_demo_status_and_system_error(
    owner_client: TestClient,
    test_settings: Settings,
    monkeypatch,
) -> None:
    run = create_waiting_test_job(
        owner_client,
        test_settings,
        monkeypatch,
    )
    job_id = run["job"]["job_id"]

    response = owner_client.post(
        "/n8n-test/callback",
        json={
            **CALLBACK_PAYLOAD,
            "job_id": job_id,
            "status": "failed",
        },
        headers={"X-Barong-Callback-Secret": TEST_CALLBACK_SECRET},
    )

    assert response.status_code == 200
    assert response.json()["job"]["status"] == "failed"
    assert response.json()["error"]["error_code"] == (
        "N8N_TEST_CALLBACK_REPORTED_FAILED"
    )


def test_webhook_http_failure_marks_job_failed_and_records_error(
    owner_client: TestClient,
    test_settings: Settings,
    monkeypatch,
) -> None:
    configure_test_bridge(test_settings)

    def failing_webhook(**kwargs):
        del kwargs
        raise TimeoutError("controlled fake timeout")

    monkeypatch.setattr(
        "backend.app.services.n8n_test_service.send_n8n_test_webhook",
        failing_webhook,
    )

    response = owner_client.post("/n8n-test/run")

    assert response.status_code == 502
    assert "marked failed" in response.json()["detail"]

    with SessionLocal() as db:
        job = db.scalar(
            select(AutomationJob)
            .where(AutomationJob.module_id == "n8n_test_bridge")
            .order_by(AutomationJob.id.desc())
        )
        system_error = db.scalar(
            select(SystemError).where(
                SystemError.error_code == "N8N_TEST_WEBHOOK_CALL_FAILED"
            )
        )
        failure_log = db.scalar(
            select(OperationLog).where(
                OperationLog.action == "n8n_test.webhook_dispatch",
                OperationLog.result == "failure",
            )
        )

    assert job is not None and job.status == "failed"
    assert job.finished_at is not None
    assert system_error is not None
    assert system_error.job_id == job.job_id
    assert system_error.details["real_business_effect"] is False
    assert failure_log is not None
    assert failure_log.details["external_http_attempted"] is True


def test_n8n_test_bridge_has_no_real_integration_or_registration_surface() -> None:
    implementation_paths = (
        REPOSITORY_ROOT / "backend" / "app" / "api" / "routes" / "n8n_test.py",
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "repositories"
        / "n8n_test.py",
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "services"
        / "n8n_test_service.py",
        REPOSITORY_ROOT
        / "backend"
        / "app"
        / "services"
        / "n8n_test_http_client.py",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in implementation_paths
    ).lower()

    for marker in (
        "import httpx",
        "import requests",
        "woocommerce.",
        "minio.",
        "filebrowser.",
        "/webhook/p",
        "real_product_created",
        "woo_product_created",
    ):
        assert marker not in source
    assert "http://" not in source
    assert "https://" not in source
    assert all(
        getattr(route, "path", "") != "/auth/register"
        for route in app.routes
    )
    assert not (
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "app"
        / "register"
        / "page.tsx"
    ).exists()
