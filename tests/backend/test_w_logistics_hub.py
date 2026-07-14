"""W-S Woo synchronization, order ingest, and 17TRACK integration tests."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from r_system_v2.core.secret_manager import SecretManager

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.user import User
from backend.app.modules.w_series import logistics
from backend.app.modules.w_series.shipping.models import (
    WOrder,
    WShippingClass,
    WSyncJob,
)

pytestmark = pytest.mark.integration

_INGEST_TOKEN = "ws-test-ingest-token"
_TRACK17_KEY = "ws-test-track17-key"
_N8N_WEBHOOK = "https://n8n.test/webhook/w-sync"


class _JSONResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> "_JSONResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _request_payload(request: urllib.request.Request) -> object:
    return json.loads((request.data or b"null").decode("utf-8"))


def _clean_logistics_rows() -> None:
    with SessionLocal() as db:
        db.execute(delete(WSyncJob))
        db.execute(delete(WOrder))
        db.execute(
            delete(WShippingClass).where(WShippingClass.slug.like("ws-test-%"))
        )
        db.commit()


def _new_order(
    *,
    woo_order_id: int,
    tracking_number: str | None = None,
    tracking_status: str = "none",
    tracking_registered: bool = False,
) -> UUID:
    with SessionLocal() as db:
        row = WOrder(
            id=uuid4(),
            woo_order_id=woo_order_id,
            order_number=f"WS-{woo_order_id}",
            woo_status="processing",
            customer_name="物流测试客户",
            country="US",
            total=Decimal("29.99"),
            currency="USD",
            items_json=[{"name": "Test item", "qty": 1, "sku": "WS-1"}],
            placed_at=datetime(2026, 7, 13, 1, 2, tzinfo=UTC),
            tracking_number=tracking_number,
            tracking_status=tracking_status,
            tracking_registered=tracking_registered,
        )
        db.add(row)
        db.commit()
        return row.id


def test_track17_response_must_match_requested_number() -> None:
    with pytest.raises(ValueError, match="17TRACK 未接受该运单号"):
        logistics._accepted_tracking_record(
            {
                "code": 0,
                "data": {
                    "accepted": [{"number": "SOMEONE-ELSES-PARCEL"}],
                    "rejected": [],
                },
            },
            "EXPECTED-PARCEL",
        )


@pytest.fixture
def logistics_env(
    owner_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    _clean_logistics_rows()
    calls: list[dict[str, object]] = []

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://console.test")
    monkeypatch.setenv("N8N_W_SYNC_WEBHOOK", _N8N_WEBHOOK)
    monkeypatch.setenv("W_ORDERS_INGEST_TOKEN", _INGEST_TOKEN)
    monkeypatch.setenv("W_17TRACK_BASE_URL", "https://track17.test")
    monkeypatch.setenv("W_17TRACK_WEBHOOK_SIGN_MODE", "sha256")
    monkeypatch.setattr(
        SecretManager,
        "get_key",
        lambda self, key_type, org_id: _TRACK17_KEY,
    )

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: int,
    ) -> _JSONResponse:
        payload = _request_payload(request)
        calls.append(
            {
                "url": request.full_url,
                "payload": payload,
                "headers": dict(request.header_items()),
                "timeout": timeout,
            }
        )
        if request.full_url.endswith("/track/v2.2/register"):
            item = payload[0]
            return _JSONResponse(
                {
                    "code": 0,
                    "data": {
                        "accepted": [
                            {
                                "number": item["number"],
                                "carrier": item.get("carrier", 0),
                            }
                        ],
                        "rejected": [],
                    },
                }
            )
        if request.full_url.endswith("/track/v2.2/gettrackinfo"):
            item = payload[0]
            return _JSONResponse(
                {
                    "code": 0,
                    "data": {
                        "accepted": [
                            {
                                "number": item["number"],
                                "track_info": {
                                    "latest_status": {"status": "Delivered"},
                                    "latest_event": {
                                        "time_utc": "2026-07-13T08:30:00Z",
                                        "location": "Seattle, WA",
                                        "description": "Delivered",
                                    },
                                    "tracking": {
                                        "providers": [
                                            {
                                                "events": [
                                                    {
                                                        "time_utc": "2026-07-13T08:30:00Z",
                                                        "location": "Seattle, WA",
                                                        "description": "Delivered",
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                },
                            }
                        ],
                        "rejected": [],
                    },
                }
            )
        return _JSONResponse({})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    yield {"client": owner_client, "calls": calls}
    _clean_logistics_rows()


def test_shipping_template_sync_state_machine_and_callback(
    logistics_env: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = logistics_env["client"]
    calls = logistics_env["calls"]
    assert isinstance(client, TestClient)
    assert isinstance(calls, list)

    response = client.post(
        "/api/app/w/shipping/classes",
        json={
            "slug": "ws-test-blank-zone",
            "name": "Invalid blank zone",
            "zone_rates_json": [
                {
                    "zone_name": "   ",
                    "base_cost": "4.99",
                    "class_cost": "2.00",
                }
            ],
            "origin": "cn_direct",
        },
    )
    assert response.status_code == 422

    response = client.post(
        "/api/app/w/shipping/classes",
        json={
            "slug": "ws-test-priority",
            "name": "Priority shipping",
            "description": "Tracked priority delivery",
            "zone_rates_json": [
                {
                    "zone_name": "United States",
                    "base_cost": "4.99",
                    "class_cost": "2.00",
                }
            ],
            "origin": "cn_direct",
            "sort_order": 15,
        },
    )
    assert response.status_code == 201, response.text
    class_id = response.json()["id"]
    assert response.json()["sync_status"] == "draft"

    response = client.post(
        f"/api/app/w/shipping/classes/{class_id}/sync"
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "dispatched"
    job_id = response.json()["job_id"]

    response = client.post(
        f"/api/app/w/shipping/classes/{class_id}/sync"
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "该模板已有同步任务在执行中。"

    response = client.patch(
        f"/api/app/w/shipping/classes/{class_id}",
        json={"name": "Must not replace the dispatched snapshot"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "该模板已有同步任务在执行中。"

    with SessionLocal() as db:
        job = db.scalar(select(WSyncJob).where(WSyncJob.job_id == job_id))
        row = db.get(WShippingClass, UUID(class_id))
        assert job is not None
        assert row is not None
        token = job.token
        assert row.sync_status == "pending"

    dispatch = next(call for call in calls if call["url"] == _N8N_WEBHOOK)
    envelope = dispatch["payload"]
    assert envelope == {
        "job_id": job_id,
        "action": "upsert_shipping_class",
        "token": token,
        "payload": {
            "slug": "ws-test-priority",
            "name": "Priority shipping",
            "description": "Tracked priority delivery",
            "woo_class_id": None,
            "zone_rates": [
                {
                    "zone_name": "United States",
                    "base_cost": "4.99",
                    "class_cost": "2.00",
                }
            ],
        },
        "callback_url": f"https://console.test/w/sync/{job_id}/result",
    }

    response = client.post(
        f"/w/sync/{job_id}/result",
        headers={"X-Job-Token": "wrong"},
        json={"status": "success", "woo_class_id": 713},
    )
    assert response.status_code == 403

    response = client.post(
        f"/w/sync/{job_id}/result",
        headers={"X-Job-Token": token},
        json={"status": "success", "woo_class_id": 713},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success"

    # A terminal callback is idempotent even if a retry carries a new outcome.
    response = client.post(
        f"/w/sync/{job_id}/result",
        headers={"X-Job-Token": token},
        json={"status": "failed", "error": "late retry"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    with SessionLocal() as db:
        row = db.get(WShippingClass, UUID(class_id))
        assert row is not None
        assert row.sync_status == "synced"
        assert row.woo_class_id == 713
        assert row.synced_at is not None
        assert row.sync_error is None

    # Missing n8n configuration is a durable pending state, not a failed save.
    monkeypatch.delenv("N8N_W_SYNC_WEBHOOK")
    response = client.post(
        "/api/app/w/shipping/classes",
        json={
            "slug": "ws-test-pending",
            "name": "Pending template",
            "origin": "cn_direct",
        },
    )
    pending_class_id = response.json()["id"]
    response = client.post(
        f"/api/app/w/shipping/classes/{pending_class_id}/sync"
    )
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["dispatched"] is False


def test_order_ingest_token_and_tracking_field_preservation(
    logistics_env: dict[str, object],
) -> None:
    client = logistics_env["client"]
    assert isinstance(client, TestClient)
    payload = {
        "orders": [
            {
                "woo_order_id": 71001,
                "order_number": "71001-A",
                "woo_status": "processing",
                "customer_name": "First customer",
                "country": "US",
                "total": "41.20",
                "currency": "USD",
                "items": [{"name": "Widget", "qty": 2, "sku": "W-7"}],
                "placed_at": "2026-07-13T02:00:00Z",
            }
        ]
    }
    assert client.post("/w/orders/ingest", json=payload).status_code == 401
    assert (
        client.post(
            "/w/orders/ingest",
            headers={"X-Ingest-Token": "wrong"},
            json=payload,
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/w/orders/ingest",
            headers={"X-Ingest-Token": f"{_INGEST_TOKEN} "},
            json=payload,
        ).status_code
        == 401
    )

    response = client.post(
        "/w/orders/ingest",
        headers={"X-Ingest-Token": _INGEST_TOKEN},
        json=payload,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"accepted": 1, "created": 1, "updated": 0}

    with SessionLocal() as db:
        order = db.scalar(select(WOrder).where(WOrder.woo_order_id == 71001))
        assert order is not None
        order.tracking_number = "TRACK-KEEP-71001"
        order.carrier_code = 3011
        order.tracking_status = "in_transit"
        order.tracking_events_json = [
            {"time": "2026-07-13T03:00:00Z", "description": "In transit"}
        ]
        order.tracking_registered = True
        order.writeback_status = "success"
        db.commit()

    response = client.post(
        "/w/orders/ingest",
        headers={"X-Ingest-Token": _INGEST_TOKEN},
        json={
            "orders": [
                {
                    "woo_order_id": 71001,
                    "order_number": "71001-A",
                    "woo_status": "completed",
                    "customer_name": "Updated customer",
                    "total": "45.00",
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"accepted": 1, "created": 0, "updated": 1}
    with SessionLocal() as db:
        order = db.scalar(select(WOrder).where(WOrder.woo_order_id == 71001))
        assert order is not None
        assert order.woo_status == "completed"
        assert order.customer_name == "Updated customer"
        assert order.tracking_number == "TRACK-KEEP-71001"
        assert order.carrier_code == 3011
        assert order.tracking_status == "in_transit"
        assert order.tracking_registered is True
        assert order.writeback_status == "success"
        assert len(order.tracking_events_json or []) == 1


def test_manual_tracking_registration_failure_is_non_blocking_and_writes_back(
    logistics_env: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = logistics_env["client"]
    calls = logistics_env["calls"]
    assert isinstance(client, TestClient)
    assert isinstance(calls, list)
    success_order_id = _new_order(woo_order_id=71002)

    response = client.patch(
        f"/api/app/w/orders/{success_order_id}/tracking",
        json={"tracking_number": "TRACK-SUCCESS-71002", "carrier_code": 3011},
    )
    assert response.status_code == 200, response.text
    assert response.json()["tracking_warning"] is None
    assert response.json()["order"]["tracking_status"] == "registered"
    assert response.json()["order"]["tracking_registered"] is True

    register_calls = sum(
        call["url"].endswith("/track/v2.2/register") for call in calls
    )
    response = client.patch(
        f"/api/app/w/orders/{success_order_id}/tracking",
        json={"tracking_number": "TRACK-SUCCESS-71002", "carrier_code": 3011},
    )
    assert response.status_code == 200, response.text
    assert (
        sum(call["url"].endswith("/track/v2.2/register") for call in calls)
        == register_calls
    )

    with SessionLocal() as db:
        order = db.get(WOrder, success_order_id)
        job = db.scalar(
            select(WSyncJob)
            .where(WSyncJob.target_type == "order_tracking")
            .where(WSyncJob.target_id == success_order_id)
        )
        assert order is not None
        assert job is not None
        assert order.writeback_status == "pending"
        assert job.status == "dispatched"
        writeback_job_id = job.job_id
        writeback_token = job.token

    writeback_call = next(
        call
        for call in calls
        if call["url"] == _N8N_WEBHOOK
        and call["payload"]["action"] == "order_tracking"
    )
    assert writeback_call["payload"]["payload"] == {
        "woo_order_id": 71002,
        "tracking_number": "TRACK-SUCCESS-71002",
        "carrier_label": "3011",
    }
    response = client.post(
        f"/w/sync/{writeback_job_id}/result",
        headers={"X-Job-Token": writeback_token},
        json={"status": "success"},
    )
    assert response.status_code == 200
    with SessionLocal() as db:
        order = db.get(WOrder, success_order_id)
        assert order is not None
        assert order.writeback_status == "success"

    failure_order_id = _new_order(woo_order_id=71003)

    def failure_urlopen(
        request: urllib.request.Request,
        timeout: int,
    ) -> _JSONResponse:
        payload = _request_payload(request)
        calls.append({"url": request.full_url, "payload": payload, "timeout": timeout})
        if request.full_url.endswith("/track/v2.2/register"):
            raise urllib.error.URLError("quota exhausted")
        return _JSONResponse({})

    monkeypatch.setattr(urllib.request, "urlopen", failure_urlopen)
    response = client.patch(
        f"/api/app/w/orders/{failure_order_id}/tracking",
        json={"tracking_number": "TRACK-FAIL-71003", "carrier_code": None},
    )
    assert response.status_code == 200, response.text
    assert response.json()["tracking_warning"] == (
        "17TRACK 注册失败：quota exhausted"
    )
    assert response.json()["order"]["tracking_status"] == "not_found"
    with SessionLocal() as db:
        order = db.get(WOrder, failure_order_id)
        job = db.scalar(
            select(WSyncJob)
            .where(WSyncJob.target_type == "order_tracking")
            .where(WSyncJob.target_id == failure_order_id)
        )
        assert order is not None
        assert job is not None
        assert order.tracking_number == "TRACK-FAIL-71003"
        assert order.tracking_registered is False
        assert order.tracking_status == "not_found"
        assert job.status == "dispatched"

    response = client.patch(
        f"/api/app/w/orders/{success_order_id}/tracking",
        json={"tracking_number": None, "carrier_code": None},
    )
    assert response.status_code == 200, response.text
    assert response.json()["order"]["tracking_number"] is None
    assert response.json()["order"]["tracking_status"] == "none"


def test_track17_webhook_signature_mapping_cap_and_idempotency(
    logistics_env: dict[str, object],
) -> None:
    client = logistics_env["client"]
    assert isinstance(client, TestClient)
    order_id = _new_order(
        woo_order_id=71004,
        tracking_number="TRACK-WEBHOOK-71004",
        tracking_status="registered",
        tracking_registered=True,
    )
    latest = datetime(2026, 7, 13, 10, 0, tzinfo=UTC)
    events = [
        {
            "time_utc": (latest - timedelta(minutes=index)).isoformat().replace(
                "+00:00", "Z"
            ),
            "location": f"Hub {index}",
            "description": f"Event {index}",
        }
        for index in range(55)
    ]
    payload = {
        "event": "TRACKING_UPDATED",
        "data": {
            "number": "TRACK-WEBHOOK-71004",
            "carrier": 3011,
            "track_info": {
                "latest_status": {"status": "InTransit"},
                "latest_event": events[0],
                "tracking": {"providers": [{"events": events}]},
            },
        },
    }
    raw_body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hashlib.sha256(
        raw_body + b"/" + _TRACK17_KEY.encode("utf-8")
    ).hexdigest()

    response = client.post(
        "/w/tracking/webhook",
        content=raw_body,
        headers={"Content-Type": "application/json", "sign": "bad-sign"},
    )
    assert response.status_code == 401

    response = client.post(
        "/w/tracking/webhook",
        content=raw_body,
        headers={"Content-Type": "application/json", "sign": signature},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"updated": 1, "ignored": 0}
    with SessionLocal() as db:
        order = db.get(WOrder, order_id)
        assert order is not None
        assert order.tracking_status == "in_transit"
        assert len(order.tracking_events_json or []) == 50
        assert order.tracking_events_json[0] == {
            "time": "2026-07-13T10:00:00Z",
            "location": "Hub 0",
            "description": "Event 0",
        }
        first_update = order.last_tracking_update

    response = client.post(
        "/w/tracking/webhook",
        content=raw_body,
        headers={"Content-Type": "application/json", "sign": signature},
    )
    assert response.status_code == 200
    assert response.json() == {"updated": 0, "ignored": 1}
    with SessionLocal() as db:
        order = db.get(WOrder, order_id)
        assert order is not None
        assert order.last_tracking_update == first_update
        assert len(order.tracking_events_json or []) == 50


def test_new_tracking_number_serializes_woo_writebacks(
    logistics_env: dict[str, object],
) -> None:
    client = logistics_env["client"]
    calls = logistics_env["calls"]
    assert isinstance(client, TestClient)
    assert isinstance(calls, list)
    order_id = _new_order(woo_order_id=71007)

    response = client.patch(
        f"/api/app/w/orders/{order_id}/tracking",
        json={"tracking_number": "TRACK-OLD-71007", "carrier_code": None},
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        old_job = db.scalar(
            select(WSyncJob)
            .where(WSyncJob.target_id == order_id)
            .order_by(WSyncJob.id.desc())
        )
        assert old_job is not None
        old_job_id = old_job.job_id
        old_token = old_job.token

    response = client.patch(
        f"/api/app/w/orders/{order_id}/tracking",
        json={"tracking_number": "TRACK-NEW-71007", "carrier_code": 3011},
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        jobs = list(
            db.scalars(
                select(WSyncJob)
                .where(WSyncJob.target_id == order_id)
                .order_by(WSyncJob.id)
            ).all()
        )
        assert len(jobs) == 2
        assert jobs[0].status == "dispatched"
        assert jobs[0].error is None
        assert jobs[1].status == "pending"
        new_job_id = jobs[1].job_id
        new_token = jobs[1].token
    n8n_calls = [call for call in calls if call["url"] == _N8N_WEBHOOK]
    assert len(n8n_calls) == 1
    assert n8n_calls[0]["payload"]["payload"]["tracking_number"] == (
        "TRACK-OLD-71007"
    )

    response = client.post(
        f"/w/sync/{old_job_id}/result",
        headers={"X-Job-Token": old_token},
        json={"status": "success"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    with SessionLocal() as db:
        order = db.get(WOrder, order_id)
        new_job = db.scalar(
            select(WSyncJob).where(WSyncJob.job_id == new_job_id)
        )
        assert order is not None
        assert new_job is not None
        assert order.tracking_number == "TRACK-NEW-71007"
        assert order.writeback_status == "pending"
        assert new_job.status == "dispatched"
    n8n_calls = [call for call in calls if call["url"] == _N8N_WEBHOOK]
    assert len(n8n_calls) == 2
    assert n8n_calls[1]["payload"]["payload"] == {
        "woo_order_id": 71007,
        "tracking_number": "TRACK-NEW-71007",
        "carrier_label": "3011",
    }

    response = client.post(
        f"/w/sync/{new_job_id}/result",
        headers={"X-Job-Token": new_token},
        json={"status": "success"},
    )
    assert response.status_code == 200
    with SessionLocal() as db:
        order = db.get(WOrder, order_id)
        assert order is not None
        assert order.writeback_status == "success"

    # A duplicated old callback cannot overwrite the latest terminal result.
    response = client.post(
        f"/w/sync/{old_job_id}/result",
        headers={"X-Job-Token": old_token},
        json={"status": "failed", "error": "late duplicate"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    with SessionLocal() as db:
        order = db.get(WOrder, order_id)
        assert order is not None
        assert order.writeback_status == "success"


def test_manual_refresh_updates_tracking_and_missing_key_is_409(
    logistics_env: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = logistics_env["client"]
    assert isinstance(client, TestClient)
    order_id = _new_order(
        woo_order_id=71005,
        tracking_number="TRACK-REFRESH-71005",
        tracking_status="registered",
        tracking_registered=True,
    )
    response = client.post(
        f"/api/app/w/orders/{order_id}/refresh-tracking"
    )
    assert response.status_code == 200, response.text
    assert response.json()["order"]["tracking_status"] == "delivered"
    assert response.json()["order"]["tracking_events_json"][0]["description"] == (
        "Delivered"
    )

    monkeypatch.setattr(
        SecretManager,
        "get_key",
        lambda self, key_type, org_id: None,
    )
    response = client.post(
        f"/api/app/w/orders/{order_id}/refresh-tracking"
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "17TRACK 密钥未绑定（去密钥管理添加）。"


def test_shipping_template_delete_lifecycle(
    logistics_env: dict[str, object],
) -> None:
    """删除三态：草稿直删；已同步派 n8n 回调后删；有产品挂靠拒绝。"""
    client = logistics_env["client"]
    calls = logistics_env["calls"]
    assert isinstance(client, TestClient)
    assert isinstance(calls, list)

    # ① 草稿（无 woo_class_id）：直接删本地，不派 n8n
    response = client.post(
        "/api/app/w/shipping/classes",
        json={"slug": "ws-del-draft", "name": "Draft only", "origin": "cn_direct"},
    )
    assert response.status_code == 201
    draft_id = response.json()["id"]
    calls_before = len(calls)
    response = client.delete(f"/api/app/w/shipping/classes/{draft_id}")
    assert response.status_code == 202
    assert response.json() == {"deleted": True, "dispatched": False}
    assert len(calls) == calls_before  # 没有 n8n 派单
    response = client.get("/api/app/w/shipping/classes")
    assert all(item["slug"] != "ws-del-draft" for item in response.json())

    # ② 已同步（有 woo_class_id）：派 delete_shipping_class，回调 success 后行删除
    with SessionLocal() as db:
        synced = WShippingClass(
            slug="ws-del-synced",
            name="Synced template",
            origin="cn_direct",
            active=True,
            sort_order=998,
            sync_status="synced",
            woo_class_id=881,
        )
        db.add(synced)
        db.commit()
        synced_id = str(synced.id)

    response = client.delete(f"/api/app/w/shipping/classes/{synced_id}")
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["deleted"] is False
    assert body["dispatched"] is True
    job_id = body["job_id"]

    dispatch = next(
        call
        for call in calls
        if call["url"] == _N8N_WEBHOOK and call["payload"]["job_id"] == job_id
    )
    assert dispatch["payload"]["action"] == "delete_shipping_class"
    assert dispatch["payload"]["payload"] == {
        "slug": "ws-del-synced",
        "woo_class_id": 881,
    }

    with SessionLocal() as db:
        job = db.scalar(select(WSyncJob).where(WSyncJob.job_id == job_id))
        assert job is not None
        token = job.token

    response = client.post(
        f"/w/sync/{job_id}/result",
        headers={"X-Job-Token": token},
        json={"status": "success"},
    )
    assert response.status_code == 200
    with SessionLocal() as db:
        assert db.get(WShippingClass, UUID(synced_id)) is None  # 行已删

    # ③ 有产品挂靠：拒绝删除
    with SessionLocal() as db:
        referenced = WShippingClass(
            slug="ws-del-referenced",
            name="Referenced template",
            origin="cn_direct",
            active=True,
            sort_order=997,
        )
        db.add(referenced)
        db.flush()
        referenced_id = str(referenced.id)
        from backend.app.modules.k_series.product_knowledge.models import (
            KProductKnowledgeProduct,
        )
        from backend.app.modules.k_series.product_knowledge.service import (
            _generate_unique_product_key,
        )

        db.add(
            KProductKnowledgeProduct(
                product_key=_generate_unique_product_key(db),
                product_name_en="WS delete guard product",
                channel="dtc",
                shipping_class="ws-del-referenced",
            )
        )
        db.commit()

    response = client.delete(f"/api/app/w/shipping/classes/{referenced_id}")
    assert response.status_code == 409
    assert "个产品挂在此模板上" in response.json()["detail"]

    with SessionLocal() as db:
        db.execute(
            text(
                "DELETE FROM k_product_knowledge_products "
                "WHERE shipping_class = 'ws-del-referenced'"
            )
        )
        db.execute(
            text("DELETE FROM w_shipping_classes WHERE slug LIKE 'ws-del-%'")
        )
        db.commit()


def test_new_human_endpoints_require_w_permissions(
    logistics_env: dict[str, object],
) -> None:
    client = logistics_env["client"]
    assert isinstance(client, TestClient)
    order_id = _new_order(
        woo_order_id=71006,
        tracking_number="TRACK-DENIED-71006",
        tracking_status="registered",
    )
    with SessionLocal() as db:
        shipping_class = WShippingClass(
            slug="ws-test-denied",
            name="Denied template",
            origin="cn_direct",
            active=True,
            sort_order=999,
        )
        db.add(shipping_class)
        db.flush()
        class_id = shipping_class.id
        username = f"ws_plain_viewer_{uuid4().hex[:8]}"
        password = "ws-example-viewer-password"
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                role="viewer",
                is_active=True,
            )
        )
        db.commit()

    response = client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    requests = (
        ("GET", "/api/app/w/orders", None),
        ("POST", f"/api/app/w/shipping/classes/{class_id}/sync", None),
        (
            "PATCH",
            f"/api/app/w/orders/{order_id}/tracking",
            {"tracking_number": "DENIED"},
        ),
        (
            "POST",
            f"/api/app/w/orders/{order_id}/refresh-tracking",
            None,
        ),
    )
    for method, path, body in requests:
        response = client.request(method, path, json=body)
        assert response.status_code == 403, f"{method} {path}: {response.text}"
