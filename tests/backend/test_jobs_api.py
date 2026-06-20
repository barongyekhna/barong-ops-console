from fastapi.testclient import TestClient


def test_jobs_api_access_layer_is_removed(owner_client: TestClient) -> None:
    list_response = owner_client.get("/api/app/jobs")
    create_response = owner_client.post(
        "/api/app/jobs",
        json={
            "job_id": "demo.job",
            "module_key": "demo.module",
            "status": "pending",
        },
    )
    detail_response = owner_client.get("/api/app/jobs/demo.job")
    events_response = owner_client.get("/api/app/jobs/demo.job/events")

    assert list_response.status_code == 404
    assert create_response.status_code == 404
    assert detail_response.status_code == 404
    assert events_response.status_code == 404
