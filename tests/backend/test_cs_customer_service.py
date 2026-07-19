from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

import backend.app.modules.cs_series.router as cs_router
from backend.app.core.config import Settings
from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.permission import UserPermissionAssignment
from backend.app.models.user import User
from backend.app.modules.cs_series.models import (
    CSMessage,
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_SCOPE_MODE,
    TARGET_ORGANIZATION_NAME,
)
from backend.app.modules.cs_series.service import (
    register_shared_inbound_rate_limit,
    reset_inbound_rate_limiter,
)
from backend.app.modules.notifications.models import PNotification
from backend.app.services.data_isolation import without_org_data_isolation
from backend.app.services.permission_service import upsert_permission_registry
from tests.fixtures.organization_fixtures import DEFAULT_TEST_ORG_DB_ID


pytestmark = pytest.mark.integration

INBOUND_KEY = "test-cs-inbound-key"
OTHER_ORG_ID = "org_22222222222222222222222222222222"
OTHER_MEMBERSHIP_ID = "mem_22222222222222222222222222222222"


def _valid_inbound(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "channel": "retail",
        "name": "Alice Customer",
        "email": "alice@example.com",
        "company": "",
        "order_number": "ORDER-100",
        "message": "Please help with my order.",
        "source_url": "https://shop.example.com/contact",
        "honeypot": "",
        "form_ms": 5000,
    }
    payload.update(overrides)
    return payload


def _post_inbound(
    client: TestClient,
    *,
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
):
    request_headers = {"X-BY-CS-KEY": INBOUND_KEY}
    if headers:
        request_headers.update(headers)
    return client.post(
        "/api/public/cs/inbound",
        json=payload or _valid_inbound(),
        headers=request_headers,
    )


def _message_count() -> int:
    with without_org_data_isolation(), SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(CSMessage)) or 0)


def _notification_count() -> int:
    with without_org_data_isolation(), SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(PNotification)) or 0)


def _single_message() -> CSMessage:
    with without_org_data_isolation(), SessionLocal() as db:
        rows = list(db.scalars(select(CSMessage)))
        assert len(rows) == 1
        db.expunge(rows[0])
        return rows[0]


def _seed_message(
    *,
    channel: str,
    status: str = "new",
    org_id: str = DEFAULT_TEST_ORG_DB_ID,
    name: str | None = None,
) -> UUID:
    row = CSMessage(
        org_id=org_id,
        workspace_key=org_id,
        business_context=DEFAULT_BUSINESS_CONTEXT,
        scope_mode=DEFAULT_SCOPE_MODE,
        organization_name=(
            TARGET_ORGANIZATION_NAME
            if org_id == DEFAULT_TEST_ORG_DB_ID
            else "隔离测试组织"
        ),
        channel=channel,
        name=name or f"{channel}-{status}",
        email=f"{channel}.{status}@example.com",
        company="Wholesale Co." if channel == "wholesale" else None,
        order_number="ORDER-SEED" if channel == "retail" else None,
        message=f"seeded {channel} {status} message",
        source_url="https://shop.example.com/contact",
        client_ip="198.51.100.10",
        user_agent="pytest",
        status=status,
    )
    with without_org_data_isolation(), SessionLocal() as db:
        db.add(row)
        db.commit()
        return row.id


def _create_other_org_owner() -> tuple[str, str]:
    username = "cs_other_org_owner"
    password = "cs-other-org-owner-password"
    with without_org_data_isolation(), SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role="owner",
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(
            OrganizationRecord(
                org_id=OTHER_ORG_ID,
                org_name="CS 隔离测试组织",
                org_type="store",
                owner_user_id=str(user.id),
                status="active",
                metadata_json={},
            )
        )
        db.flush()
        db.add(
            OrgMembershipRecord(
                membership_id=OTHER_MEMBERSHIP_ID,
                user_id=str(user.id),
                org_id=OTHER_ORG_ID,
                role="owner",
                status="active",
            )
        )
        db.commit()
    return username, password


def _create_target_member_with_permission(
    *,
    permission_key: str,
    scope_key: str,
) -> tuple[str, str]:
    username = f"cs_member_{permission_key.rsplit('.', 1)[-1]}_{scope_key[-4:]}"
    password = "cs-target-member-password"
    with without_org_data_isolation(), SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role="operator",
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(
            OrgMembershipRecord(
                membership_id=f"mem_{user.id:032x}",
                user_id=str(user.id),
                org_id=DEFAULT_TEST_ORG_DB_ID,
                role="member",
                status="active",
            )
        )
        db.add(
            UserPermissionAssignment(
                user_id=user.id,
                permission_key=permission_key,
                scope_type="organization",
                scope_key=scope_key,
                reason="CS organization-scope integration test.",
                is_enabled=True,
            )
        )
        db.commit()
    return username, password


@pytest.fixture(autouse=True)
def _reset_limiter_for_each_test() -> Iterator[None]:
    reset_inbound_rate_limiter()
    yield
    reset_inbound_rate_limiter()


@pytest.fixture
def cs_client(owner_client: TestClient, test_settings: Settings) -> TestClient:
    test_settings.cs_inbound_key = SecretStr(INBOUND_KEY)
    with SessionLocal() as db:
        upsert_permission_registry(db)
    return owner_client


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-BY-CS-KEY": "wrong-key"}],
    ids=["missing", "wrong"],
)
def test_inbound_missing_or_wrong_key_returns_exact_unauthorized_contract(
    cs_client: TestClient,
    headers: dict[str, str],
) -> None:
    response = cs_client.post(
        "/api/public/cs/inbound",
        json=_valid_inbound(),
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json() == {"ok": False}
    assert _message_count() == 0


def test_honeypot_succeeds_before_other_field_validation_without_persisting(
    cs_client: TestClient,
) -> None:
    response = _post_inbound(
        cs_client,
        payload={
            "honeypot": "filled-by-bot",
            "channel": "not-a-channel",
            "email": "not-an-email",
            "message": "",
            "form_ms": "also-invalid",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert _message_count() == 0
    assert _notification_count() == 0


def test_inbound_endpoint_returns_429_on_sixth_attempt_per_ip(
    cs_client: TestClient,
) -> None:
    headers = {"X-Forwarded-For-Origin": "203.0.113.50"}

    for index in range(5):
        response = _post_inbound(
            cs_client,
            payload=_valid_inbound(order_number=f"RATE-{index}"),
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    limited = _post_inbound(cs_client, headers=headers)
    assert limited.status_code == 429
    assert limited.json() == {"ok": False}
    assert _message_count() == 5


def test_shared_rate_limiter_rejects_twenty_first_attempt_across_sessions(
    clean_auth_tables: None,
) -> None:
    started_at = datetime(2026, 7, 19, tzinfo=UTC)
    for index in range(20):
        with SessionLocal() as db:
            assert register_shared_inbound_rate_limit(
                db,
                "203.0.113.51",
                now=started_at + timedelta(seconds=index * 61),
            )
            db.commit()

    with SessionLocal() as db:
        assert not register_shared_inbound_rate_limit(
            db,
            "203.0.113.51",
            now=started_at + timedelta(seconds=20 * 61),
        )
        db.commit()


def test_fast_submission_is_persisted_as_spam(cs_client: TestClient) -> None:
    response = _post_inbound(
        cs_client,
        payload=_valid_inbound(form_ms=2999),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert _single_message().status == "spam"


def test_inbound_fails_closed_when_target_organization_name_is_ambiguous(
    cs_client: TestClient,
) -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        owner = db.scalar(select(User).where(User.role == "owner"))
        assert owner is not None
        db.add(
            OrganizationRecord(
                org_id=OTHER_ORG_ID,
                org_name=TARGET_ORGANIZATION_NAME,
                org_type="store",
                owner_user_id=str(owner.id),
                status="active",
                metadata_json={},
            )
        )
        db.commit()

    response = _post_inbound(cs_client)
    assert response.status_code == 503
    assert response.json() == {"ok": False}
    assert _message_count() == 0


def test_forwarded_origin_ip_takes_precedence_over_socket_peer(
    cs_client: TestClient,
) -> None:
    response = _post_inbound(
        cs_client,
        headers={
            "X-Forwarded-For-Origin": " 203.0.113.77, 10.0.0.8 ",
            "User-Agent": "cs-integration-test",
        },
    )

    assert response.status_code == 200
    message = _single_message()
    assert message.client_ip == "203.0.113.77"
    assert message.user_agent == "cs-integration-test"


@pytest.mark.parametrize(
    ("channel", "title"),
    [("retail", "新零售咨询"), ("wholesale", "新批发询盘")],
)
def test_inbound_notification_has_channel_specific_route_and_org(
    cs_client: TestClient,
    channel: str,
    title: str,
) -> None:
    response = _post_inbound(
        cs_client,
        payload=_valid_inbound(channel=channel),
    )
    assert response.status_code == 200

    with without_org_data_isolation(), SessionLocal() as db:
        message = db.scalar(select(CSMessage))
        notification = db.scalar(select(PNotification))
        assert message is not None
        assert notification is not None
        route = (
            f"/cs/customer-service?channel={channel}&message={message.id}"
        )
        assert notification.org_id == DEFAULT_TEST_ORG_DB_ID
        assert notification.event_type == f"cs.inbound.{channel}"
        assert notification.title == title
        assert notification.source == "cs.customer_service"
        assert "alice@example.com" not in notification.body
        assert "Please help with my order" not in notification.body
        assert notification.external_refs == {"console_path": route}
        assert notification.payload == {
            "channel": channel,
            "message_id": str(message.id),
            "route": route,
        }


def test_notification_failure_does_not_roll_back_message(
    cs_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_notification(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("notification backend unavailable")

    monkeypatch.setattr(cs_router, "create_notification", fail_notification)

    response = _post_inbound(cs_client)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert _message_count() == 1
    assert _notification_count() == 0


def test_inbound_rejects_invalid_channel_with_public_failure_contract(
    cs_client: TestClient,
) -> None:
    response = _post_inbound(
        cs_client,
        payload=_valid_inbound(channel="all"),
    )

    assert response.status_code == 422
    assert response.json() == {"ok": False}
    assert _message_count() == 0


def test_message_list_requires_channel(cs_client: TestClient) -> None:
    response = cs_client.get("/api/app/cs/messages")

    assert response.status_code == 422


def test_retail_and_wholesale_lists_never_mix(cs_client: TestClient) -> None:
    retail_id = _seed_message(channel="retail", name="Retail only")
    wholesale_id = _seed_message(channel="wholesale", name="Wholesale only")

    retail = cs_client.get("/api/app/cs/messages?channel=retail")
    wholesale = cs_client.get("/api/app/cs/messages?channel=wholesale")

    assert retail.status_code == 200
    assert wholesale.status_code == 200
    assert retail.json()["total"] == 1
    assert wholesale.json()["total"] == 1
    assert [(item["id"], item["channel"]) for item in retail.json()["items"]] == [
        (str(retail_id), "retail")
    ]
    assert [
        (item["id"], item["channel"]) for item in wholesale.json()["items"]
    ] == [(str(wholesale_id), "wholesale")]


def test_patch_updates_status_and_sanitizes_internal_note(
    cs_client: TestClient,
) -> None:
    message_id = _seed_message(channel="retail")

    response = cs_client.patch(
        f"/api/app/cs/messages/{message_id}",
        json={
            "status": "in_progress",
            "internal_note": (
                "<b>Follow up</b>\n<script>doBadThing()</script>  Tomorrow"
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"
    assert response.json()["internal_note"] == "Follow up\nTomorrow"
    detail = cs_client.get(f"/api/app/cs/messages/{message_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "in_progress"
    assert detail.json()["internal_note"] == "Follow up\nTomorrow"


def test_summary_counts_only_current_org_new_messages_and_foreign_rows_are_hidden(
    cs_client: TestClient,
) -> None:
    _seed_message(channel="retail", status="new", name="Retail one")
    _seed_message(channel="retail", status="new", name="Retail two")
    _seed_message(channel="retail", status="resolved", name="Retail resolved")
    _seed_message(channel="wholesale", status="new", name="Wholesale one")
    foreign_id = _seed_message(
        channel="retail",
        status="new",
        org_id=OTHER_ORG_ID,
        name="Foreign retail",
    )
    _seed_message(
        channel="wholesale",
        status="new",
        org_id=OTHER_ORG_ID,
        name="Foreign wholesale",
    )

    summary = cs_client.get("/api/app/cs/summary")
    retail = cs_client.get("/api/app/cs/messages?channel=retail")
    foreign_detail = cs_client.get(f"/api/app/cs/messages/{foreign_id}")
    foreign_patch = cs_client.patch(
        f"/api/app/cs/messages/{foreign_id}",
        json={"status": "resolved"},
    )

    assert summary.status_code == 200
    assert summary.json() == {
        "retail": {"new": 2},
        "wholesale": {"new": 1},
    }
    assert retail.status_code == 200
    assert retail.json()["total"] == 3
    assert {item["name"] for item in retail.json()["items"]} == {
        "Retail one",
        "Retail two",
        "Retail resolved",
    }
    assert foreign_detail.status_code == 404
    assert foreign_patch.status_code == 404


def test_permission_from_another_organization_cannot_read_target_messages(
    cs_client: TestClient,
) -> None:
    username, password = _create_target_member_with_permission(
        permission_key="cs.customer_service.read",
        scope_key=OTHER_ORG_ID,
    )
    cs_client.cookies.clear()
    login = cs_client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200

    response = cs_client.get("/api/app/cs/messages?channel=retail")
    assert response.status_code == 403


def test_target_scoped_read_permission_cannot_update_message(
    cs_client: TestClient,
) -> None:
    message_id = _seed_message(channel="retail")
    username, password = _create_target_member_with_permission(
        permission_key="cs.customer_service.read",
        scope_key=DEFAULT_TEST_ORG_DB_ID,
    )
    cs_client.cookies.clear()
    login = cs_client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200

    listing = cs_client.get("/api/app/cs/messages?channel=retail")
    update = cs_client.patch(
        f"/api/app/cs/messages/{message_id}",
        json={"status": "resolved"},
    )
    assert listing.status_code == 200
    assert update.status_code == 403


def test_cs_notification_is_not_visible_to_another_organization(
    cs_client: TestClient,
) -> None:
    assert _post_inbound(cs_client).status_code == 200
    with without_org_data_isolation(), SessionLocal() as db:
        notification = db.scalar(select(PNotification))
        assert notification is not None
        notification_id = notification.id
        assert notification.org_id == DEFAULT_TEST_ORG_DB_ID

    owner_notifications = cs_client.get("/api/app/notifications")
    assert owner_notifications.status_code == 200
    assert notification_id in {
        item["id"] for item in owner_notifications.json()["items"]
    }

    username, password = _create_other_org_owner()
    cs_client.cookies.clear()
    login = cs_client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200

    other_org_notifications = cs_client.get("/api/app/notifications")
    other_org_cs = cs_client.get("/api/app/cs/messages?channel=retail")
    assert other_org_notifications.status_code == 200
    assert other_org_cs.status_code == 403
    assert notification_id not in {
        item["id"] for item in other_org_notifications.json()["items"]
    }
