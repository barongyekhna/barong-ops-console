from fastapi.testclient import TestClient


def module_payload(module_key: str = "demo.module") -> dict:
    return {
        "module_key": module_key,
        "name": "Demo module",
        "status": "foundation",
    }


def create_module(
    client: TestClient, module_key: str = "demo.module"
) -> dict:
    response = client.post("/modules", json=module_payload(module_key))
    assert response.status_code == 201, response.text
    return response.json()


def create_agent(
    client: TestClient,
    agent_key: str = "demo.agent",
    module_key: str = "demo.module",
) -> dict:
    response = client.post(
        "/agents",
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
    response = client.post(
        "/workflows",
        json={
            "workflow_key": workflow_key,
            "name": "Demo workflow metadata",
            "status": "demo",
            "engine": "metadata_only",
            "endpoint_ref": "foundation://metadata-only",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_job(
    client: TestClient,
    job_id: str = "demo.job",
    module_key: str = "demo.module",
) -> dict:
    response = client.post(
        "/jobs",
        json={
            "job_id": job_id,
            "module_key": module_key,
            "status": "pending",
            "input_payload": {"purpose": "foundation API test"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
