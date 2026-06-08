from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models.operation_log import OperationLog
from tests.backend.foundation_helpers import create_job, create_module


def prepare_job(client: TestClient) -> None:
    create_module(client)
    create_job(client)


def test_artifact_registers_metadata_without_file_upload(
    owner_client: TestClient,
) -> None:
    prepare_job(owner_client)

    response = owner_client.post(
        "/artifacts",
        json={
            "artifact_id": "demo.artifact",
            "job_id": "demo.job",
            "module_key": "demo.module",
            "artifact_type": "demo_report",
            "name": "Demo report metadata",
            "storage_provider": "metadata_only",
            "storage_ref": "foundation://metadata-only",
            "metadata": {"uploaded": False},
        },
    )
    blocked_network_ref = owner_client.post(
        "/artifacts",
        json={
            "artifact_id": "demo.network-artifact",
            "job_id": "demo.job",
            "module_key": "demo.module",
            "artifact_type": "demo_report",
            "name": "Blocked storage reference",
            "storage_ref": "s3://example-bucket/object",
        },
    )

    assert response.status_code == 201
    assert response.json()["storage_provider"] == "metadata_only"
    assert response.json()["metadata"]["uploaded"] is False
    assert blocked_network_ref.status_code == 422


def test_review_creation_and_demo_decision_are_audited(
    owner_client: TestClient,
) -> None:
    prepare_job(owner_client)

    created = owner_client.post(
        "/reviews",
        json={
            "review_id": "demo.review",
            "job_id": "demo.job",
            "review_type": "foundation_check",
        },
    )
    decided = owner_client.post(
        "/reviews/demo.review/decision",
        json={
            "decision": "approve_demo",
            "comment": "Demo approval only.",
        },
    )

    assert created.status_code == 201
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved_demo"
    assert decided.json()["decision"] == "approve_demo"

    with SessionLocal() as db:
        actions = set(
            db.scalars(
                select(OperationLog.action).where(
                    OperationLog.target_id == "demo.review"
                )
            )
        )
        decision_log = db.scalar(
            select(OperationLog).where(
                OperationLog.action == "review.decision_demo"
            )
        )
    assert actions == {"review.create_demo", "review.decision_demo"}
    assert decision_log is not None
    assert decision_log.details["downstream_triggered"] is False


def test_system_error_records_only_demo_error_metadata(
    owner_client: TestClient,
) -> None:
    prepare_job(owner_client)

    response = owner_client.post(
        "/errors",
        json={
            "error_id": "demo.error",
            "error_code": "FOUNDATION_TEST_ERROR",
            "message": "Controlled foundation error record.",
            "job_id": "demo.job",
        },
    )

    assert response.status_code == 201
    assert response.json()["severity"] == "error_demo"
    assert response.json()["status"] == "open_demo"
