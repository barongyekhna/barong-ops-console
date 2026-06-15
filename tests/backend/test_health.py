from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/public/health")

    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "barong-ops-console-backend"
    assert payload["database"] == "not_configured"
    assert payload["external_services"] == "not_connected"

    sensitive_markers = ("secret", "token", "password", "key")
    assert not any(
        marker in field.lower()
        for field in payload
        for marker in sensitive_markers
    )
