import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from tests.backend.foundation_helpers import create_job, create_module

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def prepare_job(client: TestClient) -> None:
    create_module(client)
    create_job(client)


def test_memory_event_and_context_packet_do_not_call_models(
    owner_client: TestClient,
) -> None:
    prepare_job(owner_client)

    memory_event = owner_client.post(
        "/api/app/memory-events",
        json={
            "memory_event_id": "demo.memory-event",
            "event_type": "foundation_note",
            "subject_type": "job",
            "subject_id": "demo.job",
            "job_id": "demo.job",
            "payload": {"summary": "No model was called."},
        },
    )
    context_packet = owner_client.post(
        "/api/app/context-packets",
        json={
            "context_packet_id": "demo.context-packet",
            "source_job_id": "demo.job",
            "source_module_key": "demo.module",
            "target_module_key": "demo.module",
            "payload": {"purpose": "foundation handoff"},
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat(),
        },
    )

    assert memory_event.status_code == 201
    assert memory_event.json()["created_by_type"] == "user"
    assert context_packet.status_code == 201

    operation_logs = owner_client.get("/api/app/operation-logs").json()["items"]
    relevant_logs = {
        item["action"]: item
        for item in operation_logs
        if item["action"]
        in {"memory_event.create_demo", "context_packet.create_demo"}
    }
    assert relevant_logs["memory_event.create_demo"]["details"][
        "model_called"
    ] is False
    assert relevant_logs["context_packet.create_demo"]["details"][
        "model_called"
    ] is False


def test_operation_logs_are_read_only_and_responses_exclude_secrets(
    owner_client: TestClient,
) -> None:
    create_module(owner_client)
    create_job(owner_client)

    listed = owner_client.get("/api/app/operation-logs")
    operation_id = listed.json()["items"][0]["operation_id"]
    detail = owner_client.get(f"/api/app/operation-logs/{operation_id}")
    post = owner_client.post("/api/app/operation-logs", json={})
    delete = owner_client.delete(f"/api/app/operation-logs/{operation_id}")

    assert listed.status_code == 200
    assert detail.status_code == 200
    assert post.status_code == 405
    assert delete.status_code == 405

    serialized = json.dumps(
        {"list": listed.json(), "detail": detail.json()}
    ).lower()
    assert "password_hash" not in serialized
    assert '"token"' not in serialized
    assert '"secret"' not in serialized


def test_f10_runtime_code_has_no_external_http_clients() -> None:
    inspected_roots = (
        REPOSITORY_ROOT / "backend" / "app" / "api" / "routes",
        REPOSITORY_ROOT / "backend" / "app" / "repositories",
        REPOSITORY_ROOT / "backend" / "app" / "services",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for root in inspected_roots
        for path in root.glob("*.py")
        if not path.name.startswith("n8n_test")
    )

    assert "import httpx" not in source
    assert "import requests" not in source
    assert "urllib.request" not in source
