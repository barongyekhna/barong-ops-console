from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.api_keys import ApiKeyRecord
from backend.app.models.key_health import KeyHealthCheck, KeyHealthRun, KeyHealthState
from backend.app.models.organization import OrganizationRecord
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.user import User
from backend.app.modules.key_health.probes import ProbeResult
from backend.app.modules.key_health.service import (
    RUNTIME_INCIDENT_KEY,
    report_runtime_incident,
    report_runtime_recovered,
    run_key_health_check,
)
from backend.app.modules.notifications.models import PNotification
from backend.app.modules.notifications.service import create_notification
from tests.fixtures.organization_fixtures import DEFAULT_TEST_ORG_DB_ID


pytestmark = pytest.mark.integration


def test_health_run_never_mutates_api_key_records(
    owner_client: TestClient,
    monkeypatch,
) -> None:
    created = owner_client.post(
        "/api/control-plane/api-key-orchestration/organizations/"
        f"{DEFAULT_TEST_ORG_DB_ID}/keys",
        json={
            "name": "health-safe-key",
            "url": "https://api.deepseek.com",
            "key_value": "health-safe-secret",
            "key_type": "deepseek",
        },
    )
    assert created.status_code == 201, created.text
    key_id = created.json()["item"]["key_id"]

    with SessionLocal() as db:
        before = db.scalar(select(ApiKeyRecord).where(ApiKeyRecord.key_id == key_id))
        assert before is not None
        immutable_snapshot = (
            before.encrypted_key_value,
            before.status,
            before.updated_at,
            dict(before.metadata_json),
        )

    def healthy_probe(target):
        assert target.key_id == key_id
        assert target.secret_value == "health-safe-secret"
        return ProbeResult(
            adapter="deepseek",
            status="healthy",
            reason_code="models_list_ok",
            latency_ms=12,
            checked_at=datetime.now(UTC),
            http_status=200,
            details={"models_visible": 2},
        )

    monkeypatch.setattr(
        "backend.app.modules.key_health.service.safe_probe_target",
        healthy_probe,
    )
    outcome = run_key_health_check(
        trigger="test",
        scheduled_for=datetime(2098, 1, 1, tzinfo=UTC),
    )
    assert outcome.status == "completed"
    assert outcome.healthy_count == 1

    with SessionLocal() as db:
        after = db.scalar(select(ApiKeyRecord).where(ApiKeyRecord.key_id == key_id))
        assert after is not None
        assert (
            after.encrypted_key_value,
            after.status,
            after.updated_at,
            dict(after.metadata_json),
        ) == immutable_snapshot
        assert db.scalar(select(KeyHealthRun).where(KeyHealthRun.id == outcome.run_id))
        assert db.scalar(select(KeyHealthCheck).where(KeyHealthCheck.key_id == key_id))
        state = db.scalar(select(KeyHealthState).where(KeyHealthState.key_id == key_id))
        assert state is not None
        assert state.current_status == "healthy"

    summary = owner_client.get("/api/control-plane/key-health/summary")
    assert summary.status_code == 200, summary.text
    item = next(row for row in summary.json()["items"] if row["key_id"] == key_id)
    assert item["status"] == "healthy"
    assert item["details"]["latency_ms"] == 12


def test_owner_targeted_notification_is_hidden_from_other_users(
    auth_client: TestClient,
) -> None:
    owner_password = "owner-notification-password"
    user_password = "regular-notification-password"
    with SessionLocal() as db:
        owner = User(
            username="key_health_owner",
            password_hash=hash_password(owner_password),
            role="owner",
            is_active=True,
            must_change_password=False,
        )
        regular = User(
            username="key_health_regular",
            password_hash=hash_password(user_password),
            role="member",
            is_active=True,
            must_change_password=False,
        )
        db.add_all((owner, regular))
        db.flush()
        owner.organization_id = DEFAULT_TEST_ORG_DB_ID
        regular.organization_id = DEFAULT_TEST_ORG_DB_ID
        db.add(
            OrganizationRecord(
                org_id=DEFAULT_TEST_ORG_DB_ID,
                org_name="Key Health Test Organization",
                org_type="store",
                owner_user_id=str(owner.id),
                status="active",
                metadata_json={},
            )
        )
        db.flush()
        db.add_all(
            (
                OrgMembershipRecord(
                    membership_id="membership_key_health_owner",
                    user_id=str(owner.id),
                    org_id=DEFAULT_TEST_ORG_DB_ID,
                    role="owner",
                    status="active",
                ),
                OrgMembershipRecord(
                    membership_id="membership_key_health_regular",
                    user_id=str(regular.id),
                    org_id=DEFAULT_TEST_ORG_DB_ID,
                    role="member",
                    status="active",
                ),
            )
        )
        private = create_notification(
            db,
            event_type="key_health.failed",
            title="owner private alert",
            source="key.health",
            recipient_user_id=str(owner.id),
        )
        create_notification(
            db,
            event_type="system.global",
            title="global alert",
            source="system",
        )
        private_id = private.id
        db.commit()

    login = auth_client.post(
        "/api/public/auth/login",
        json={"username": "key_health_regular", "password": user_password},
    )
    assert login.status_code == 200, login.text
    regular_items = auth_client.get("/api/app/notifications")
    assert regular_items.status_code == 200, regular_items.text
    assert [item["title"] for item in regular_items.json()["items"]] == ["global alert"]
    blocked_read = auth_client.post(f"/api/app/notifications/{private_id}/read")
    assert blocked_read.status_code == 200
    assert blocked_read.json()["updated"] == 0
    forbidden_health = auth_client.get("/api/control-plane/key-health/summary")
    assert forbidden_health.status_code == 403

    auth_client.post("/api/public/auth/logout")
    login = auth_client.post(
        "/api/public/auth/login",
        json={"username": "key_health_owner", "password": owner_password},
    )
    assert login.status_code == 200, login.text
    owner_items = auth_client.get("/api/app/notifications")
    assert owner_items.status_code == 200, owner_items.text
    assert {item["title"] for item in owner_items.json()["items"]} == {
        "global alert",
        "owner private alert",
    }

    with SessionLocal() as db:
        private_row = db.get(PNotification, private_id)
        assert private_row is not None
        assert private_row.status == "unread"


def test_runtime_incident_survives_healthy_probe_until_recovered(
    owner_client: TestClient,
    monkeypatch,
) -> None:
    """业务 worker 回报「额度用完」后，零消耗探针的 healthy 不能把它冲绿。

    2026-09-05 事故：DeepSeek 402 / 1688 NoUsageLeft 刷了三天，健康页一直绿。
    """
    created = owner_client.post(
        "/api/control-plane/api-key-orchestration/organizations/"
        f"{DEFAULT_TEST_ORG_DB_ID}/keys",
        json={
            "name": "1688 官方 API",
            "url": "https://gw.open.1688.com",
            "key_value": '{"app_key":"k","app_secret":"s","access_token":"t"}',
            "key_type": "alibaba1688",
        },
    )
    assert created.status_code == 201, created.text
    key_id = created.json()["item"]["key_id"]

    matched = report_runtime_incident(
        key_type="alibaba1688",
        reason_code="provider_quota_exhausted",
        message="1688 分销图搜：SLA bill has no usage left",
        source="r-a-worker",
    )
    assert matched == 1
    with SessionLocal() as db:
        state = db.scalar(select(KeyHealthState).where(KeyHealthState.key_id == key_id))
        assert state is not None
        assert state.current_status == "provider_error"
        assert state.reason_code == "provider_quota_exhausted"
        assert state.details_json[RUNTIME_INCIDENT_KEY]["source"] == "r-a-worker"

    def healthy_probe(target):
        return ProbeResult(
            adapter="alibaba1688",
            status="healthy",
            reason_code="credential_structure_and_gateway_ok",
            latency_ms=5,
            checked_at=datetime.now(UTC),
            http_status=200,
            details={"check_depth": "non_consuming"},
        )

    monkeypatch.setattr(
        "backend.app.modules.key_health.service.safe_probe_target",
        healthy_probe,
    )
    run_key_health_check(trigger="test", scheduled_for=datetime(2098, 1, 2, tzinfo=UTC))
    with SessionLocal() as db:
        state = db.scalar(select(KeyHealthState).where(KeyHealthState.key_id == key_id))
        assert state is not None
        assert state.current_status == "provider_error"
        assert state.reason_code == "provider_quota_exhausted"
        assert RUNTIME_INCIDENT_KEY in state.details_json
        assert state.details_json["check_depth"] == "non_consuming"

    assert report_runtime_recovered(key_type="alibaba1688", source="r-a-worker") == 1
    with SessionLocal() as db:
        state = db.scalar(select(KeyHealthState).where(KeyHealthState.key_id == key_id))
        assert state is not None
        assert state.current_status == "healthy"
        assert state.reason_code == "runtime_call_ok"
        assert RUNTIME_INCIDENT_KEY not in state.details_json

    run_key_health_check(trigger="test", scheduled_for=datetime(2098, 1, 3, tzinfo=UTC))
    with SessionLocal() as db:
        state = db.scalar(select(KeyHealthState).where(KeyHealthState.key_id == key_id))
        assert state is not None
        assert state.current_status == "healthy"
        assert state.reason_code == "credential_structure_and_gateway_ok"
