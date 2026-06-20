import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models.operation_log import OperationLog
from tests.backend.foundation_helpers import (
    create_module,
    module_payload,
)

F10_LIST_PATHS = (
    "/api/control-plane/modules",
    "/api/control-plane/agents",
    "/api/app/artifacts",
    "/api/app/reviews",
    "/api/app/errors",
    "/api/app/memory-events",
    "/api/app/context-packets",
    "/api/app/memory-summaries",
    "/api/app/operation-logs",
)

REMOVED_MODULE_PATHS = (
    "/api/control-plane/workflows",
    "/api/control-plane/workflows/demo.workflow",
    "/api/app/jobs",
    "/api/app/jobs/demo.job",
    "/api/app/jobs/demo.job/events",
)


@pytest.mark.parametrize("path", F10_LIST_PATHS)
def test_f10_lists_require_authentication(
    auth_client: TestClient,
    path: str,
) -> None:
    response = auth_client.get(path)

    assert response.status_code == 401


@pytest.mark.parametrize("path", F10_LIST_PATHS)
def test_owner_can_access_f10_lists(
    owner_client: TestClient,
    path: str,
) -> None:
    response = owner_client.get(path)

    assert response.status_code == 200
    if path == "/api/app/operation-logs":
        assert response.json()["items"][0]["action"] == "auth.login"
    else:
        assert response.json()["items"] == []


@pytest.mark.parametrize("path", REMOVED_MODULE_PATHS)
def test_jobs_and_workflows_routes_are_removed(
    owner_client: TestClient,
    path: str,
) -> None:
    response = owner_client.get(path)

    assert response.status_code == 404


def test_create_module_and_duplicate_conflict(
    owner_client: TestClient,
) -> None:
    payload = module_payload()

    created = owner_client.post("/api/control-plane/modules", json=payload)
    duplicate = owner_client.post("/api/control-plane/modules", json=payload)

    assert created.status_code == 201
    assert created.json()["module_key"] == payload["module_key"]
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]

    with SessionLocal() as db:
        log = db.scalar(
            select(OperationLog).where(
                OperationLog.action == "module.create_demo"
            )
        )
    assert log is not None
    assert log.target_id == payload["module_key"]
    assert log.result == "success"


def test_create_demo_agent_metadata(
    owner_client: TestClient,
) -> None:
    create_module(owner_client)

    agent = owner_client.post(
        "/api/control-plane/agents",
        json={
            "agent_key": "demo.agent",
            "name": "Demo agent",
            "status": "demo",
            "allowed_module_keys": ["demo.module"],
        },
    )

    assert agent.status_code == 201
    assert agent.json()["agent_key"] == "demo.agent"

    serialized = json.dumps([agent.json()]).lower()
    assert "password_hash" not in serialized
    assert '"token"' not in serialized
    assert '"secret"' not in serialized


def test_workflows_api_access_layer_is_removed(
    owner_client: TestClient,
) -> None:
    network_endpoint = owner_client.post(
        "/api/control-plane/workflows",
        json={
            "workflow_key": "demo.network-workflow",
            "name": "Blocked network workflow",
            "endpoint_ref": "https://example.invalid/hook",
        },
    )
    credential_contract = owner_client.post(
        "/api/control-plane/workflows",
        json={
            "workflow_key": "demo.credential-workflow",
            "name": "Blocked credential workflow",
            "callback_contract": {"api_key": "not-accepted"},
        },
    )

    assert network_endpoint.status_code == 404
    assert credential_contract.status_code == 404
