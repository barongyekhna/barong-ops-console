from fastapi.testclient import TestClient

from backend.app.db.session import SessionLocal
from backend.app.models.job import AutomationJob
from backend.app.models.registry import WorkflowRegistry

DEFAULT_TEST_ORG_ID = "org_11111111111111111111111111111111"


def module_payload(module_key: str = "demo.module") -> dict:
    return {
        "module_key": module_key,
        "name": "Demo module",
        "status": "foundation",
    }


def create_module(
    client: TestClient, module_key: str = "demo.module"
) -> dict:
    response = client.post("/api/control-plane/modules", json=module_payload(module_key))
    assert response.status_code == 201, response.text
    return response.json()


def create_agent(
    client: TestClient,
    agent_key: str = "demo.agent",
    module_key: str = "demo.module",
) -> dict:
    response = client.post(
        "/api/control-plane/agents",
        json={
            "agent_key": agent_key,
            "name": "Demo agent",
            "status": "demo",
            "allowed_module_keys": [module_key],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_workflow(
    client: TestClient,
    workflow_key: str = "demo.workflow",
) -> dict:
    del client
    with SessionLocal() as db:
        workflow = WorkflowRegistry(
            workflow_id=workflow_key,
            name="Demo workflow metadata",
            status="demo",
            engine="metadata_only",
            endpoint_ref="foundation://metadata-only",
            timeout_seconds=60,
            callback_contract={},
            retry_policy={},
        )
        db.add(workflow)
        db.commit()
        return {
            "workflow_key": workflow.workflow_id,
            "name": workflow.name,
            "status": workflow.status,
            "engine": workflow.engine,
            "endpoint_ref": workflow.endpoint_ref,
        }


def create_job(
    client: TestClient,
    job_id: str = "demo.job",
    module_key: str = "demo.module",
) -> dict:
    del client
    with SessionLocal() as db:
        job = AutomationJob(
            org_id=DEFAULT_TEST_ORG_ID,
            job_id=job_id,
            module_id=module_key,
            agent_id=None,
            workflow_id=None,
            parent_job_id=None,
            requested_by_user_id=None,
            status="pending",
            risk_level="low",
            input_payload={"purpose": "foundation API test"},
            input_schema_version="0.1.0-demo",
            idempotency_key=None,
            correlation_id=None,
        )
        db.add(job)
        db.commit()
        return {
            "job_id": job.job_id,
            "module_key": job.module_id,
            "status": job.status,
            "input_payload": job.input_payload,
        }
