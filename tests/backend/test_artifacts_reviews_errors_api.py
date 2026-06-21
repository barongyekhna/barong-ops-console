from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models.artifact import Artifact
from backend.app.models.operation_log import OperationLog
from tests.backend.foundation_helpers import create_job, create_module


def prepare_job(client: TestClient) -> None:
    create_module(client)
    create_job(client)


def test_artifacts_api_access_layer_is_removed_without_deleting_data(
    owner_client: TestClient,
) -> None:
    prepare_job(owner_client)

    with SessionLocal() as db:
        before_count = db.query(Artifact).count()

    response = owner_client.post(
        "/api/app/artifacts",
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
    list_response = owner_client.get("/api/app/artifacts")

    assert response.status_code == 404
    assert list_response.status_code == 404
    with SessionLocal() as db:
        assert db.query(Artifact).count() == before_count


def test_review_creation_and_demo_decision_are_audited(
    owner_client: TestClient,
) -> None:
    prepare_job(owner_client)

    created = owner_client.post(
        "/api/app/reviews",
        json={
            "review_id": "demo.review",
            "job_id": "demo.job",
            "review_type": "foundation_check",
        },
    )
    decided = owner_client.post(
        "/api/app/reviews/demo.review/decision",
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
        "/api/app/errors",
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
