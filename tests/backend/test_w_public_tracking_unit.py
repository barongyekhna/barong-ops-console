"""Public buyer tracking endpoint contract and safety tests."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.modules.w_series.router as w_router
from backend.app.core.config import Settings, get_settings
from backend.app.main import app as main_app
from backend.app.models.security import SecurityRateLimitBucket
from backend.app.modules.w_series import logistics
from backend.app.modules.w_series.shipping.models import WOrder


pytestmark = pytest.mark.unit

TRACK_PUBLIC_KEY = "test-track-public-key"
TRACK_PATH = "/api/public/track/lookup"


@dataclass
class PublicTrackHarness:
    app: FastAPI
    sessions: sessionmaker[Session]

    def _post(
        self,
        *,
        headers: dict[str, str],
        **request_kwargs: Any,
    ) -> Response:
        async def request() -> Response:
            async with AsyncClient(
                transport=ASGITransport(app=self.app),
                base_url="http://testserver",
            ) as client:
                return await client.post(
                    TRACK_PATH,
                    headers=headers,
                    **request_kwargs,
                )

        return asyncio.run(request())

    def post(
        self,
        *,
        payload: dict[str, object],
        headers: dict[str, str],
    ) -> Response:
        return self._post(headers=headers, json=payload)

    def post_content(
        self,
        *,
        content: bytes,
        headers: dict[str, str],
    ) -> Response:
        return self._post(headers=headers, content=content)


@pytest.fixture
def public_track_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[PublicTrackHarness]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    WOrder.__table__.create(engine)
    SecurityRateLimitBucket.__table__.create(engine)
    sessions = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(w_router, "SessionLocal", sessions)

    # Keep the unit test deterministic by running the endpoint's sync worker
    # inline; production still uses AnyIO's worker thread.
    async def run_sync_inline(function, *args, **kwargs):
        del kwargs
        return function(*args)

    monkeypatch.setattr(w_router.to_thread, "run_sync", run_sync_inline)

    settings = Settings(track_public_key=SecretStr(TRACK_PUBLIC_KEY))
    test_app = FastAPI()
    test_app.include_router(w_router.public_router, prefix="/api/public")

    async def settings_override() -> Settings:
        return settings

    test_app.dependency_overrides[get_settings] = settings_override
    yield PublicTrackHarness(app=test_app, sessions=sessions)
    engine.dispose()


def _headers(key: str = TRACK_PUBLIC_KEY) -> dict[str, str]:
    return {"X-BY-TRACK-KEY": key}


def _seed_order(
    harness: PublicTrackHarness,
    *,
    woo_order_id: int,
    order_number: str,
    tracking_number: str | None,
    tracking_status: str = "none",
    carrier_code: int | None = None,
    events: list[dict[str, object]] | None = None,
    last_update: datetime | None = None,
    customer_name: str | None = None,
    total: Decimal | None = None,
    items: list[dict[str, object]] | None = None,
) -> None:
    now = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
    with harness.sessions() as db:
        db.add(
            WOrder(
                id=uuid4(),
                woo_order_id=woo_order_id,
                order_number=order_number,
                woo_status="processing",
                customer_name=customer_name,
                country="US",
                total=total,
                currency="USD",
                items_json=items,
                placed_at=now,
                tracking_number=tracking_number,
                carrier_code=carrier_code,
                tracking_status=tracking_status,
                tracking_events_json=events,
                tracking_registered=bool(tracking_number),
                last_tracking_update=last_update,
                writeback_status="none",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()


@pytest.mark.parametrize(
    "headers",
    [{}, _headers("wrong-key")],
    ids=["missing", "wrong"],
)
def test_missing_or_wrong_key_returns_exact_unauthorized_contract(
    public_track_harness: PublicTrackHarness,
    headers: dict[str, str],
) -> None:
    response = public_track_harness.post(
        payload={"order_numbers": ["3864"]},
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json() == {"ok": False}
    assert "detail" not in response.text
    with public_track_harness.sessions() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(SecurityRateLimitBucket)
            )
            == 0
        )


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "application/json"},
        {**_headers("wrong-key"), "Content-Type": "application/json"},
    ],
    ids=["missing", "wrong"],
)
def test_unauthorized_request_is_rejected_before_malformed_body(
    public_track_harness: PublicTrackHarness,
    headers: dict[str, str],
) -> None:
    response = public_track_harness.post_content(
        content=b"{not-json",
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json() == {"ok": False}


def test_mixed_lookup_preserves_order_states_events_and_excludes_pii(
    public_track_harness: PublicTrackHarness,
) -> None:
    customer_sentinel = "PRIVATE-CUSTOMER-NAME-7c67"
    total_sentinel = Decimal("98765.43")
    item_sentinel = "PRIVATE-ITEM-SKU-a901"
    event_internal_sentinel = "PRIVATE-EVENT-METADATA-c54d"
    events = [
        {
            "time": "2026-07-20T10:00:00Z",
            "location": "Los Angeles, US",
            "description": "Arrived at facility",
            "internal_note": event_internal_sentinel,
        },
        {
            "time": "2026-07-18T09:00:00Z",
            "location": "Shenzhen, CN",
            "description": "Picked up",
        },
    ]
    _seed_order(
        public_track_harness,
        woo_order_id=3864,
        order_number="3864",
        tracking_number="SF1234567890",
        tracking_status="in_transit",
        carrier_code=100003,
        events=events,
        last_update=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
        customer_name=customer_sentinel,
        total=total_sentinel,
        items=[{"sku": item_sentinel, "name": "Private item"}],
    )
    _seed_order(
        public_track_harness,
        woo_order_id=3855,
        order_number="3855",
        tracking_number=None,
        customer_name="Another private customer",
    )

    requested = ["3864", "9999", "3855", "3864"]
    response = public_track_harness.post(
        payload={"order_numbers": requested},
        headers=_headers(),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["order_number"] for item in payload["results"]] == requested
    assert [item["state"] for item in payload["results"]] == [
        "tracked",
        "unknown",
        "not_shipped",
        "tracked",
    ]

    tracked = payload["results"][0]
    assert tracked == {
        "order_number": "3864",
        "state": "tracked",
        "tracking_number": "SF1234567890",
        "carrier_code": 100003,
        "tracking_status": "in_transit",
        "last_update": "2026-07-20T10:00:00Z",
        "events": [
            {
                "time": "2026-07-20T10:00:00Z",
                "location": "Los Angeles, US",
                "description": "Arrived at facility",
            },
            {
                "time": "2026-07-18T09:00:00Z",
                "location": "Shenzhen, CN",
                "description": "Picked up",
            },
        ],
    }
    assert payload["results"][1] == {
        "order_number": "9999",
        "state": "unknown",
        "tracking_number": None,
        "carrier_code": None,
        "tracking_status": None,
        "last_update": None,
        "events": [],
    }
    assert payload["results"][2] == {
        "order_number": "3855",
        "state": "not_shipped",
        "tracking_number": None,
        "carrier_code": None,
        "tracking_status": None,
        "last_update": None,
        "events": [],
    }

    allowed_keys = {
        "order_number",
        "state",
        "tracking_number",
        "carrier_code",
        "tracking_status",
        "last_update",
        "events",
    }
    assert all(set(item) == allowed_keys for item in payload["results"])
    forbidden_keys = {
        "id",
        "customer_name",
        "email",
        "phone",
        "address",
        "total",
        "currency",
        "items_json",
        "woo_status",
    }
    assert all(forbidden_keys.isdisjoint(item) for item in payload["results"])
    for sentinel in (
        customer_sentinel,
        str(total_sentinel),
        item_sentinel,
        event_internal_sentinel,
    ):
        assert sentinel not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"order_numbers": []},
        {"order_numbers": [str(index) for index in range(21)]},
        {"order_numbers": [f"  {'x' * 65}  "]},
        {"order_numbers": ["3864"], "relay_extra": True},
    ],
    ids=["empty", "twenty-one", "too-long-after-trim", "extra"],
)
def test_invalid_lookup_payloads_return_422(
    public_track_harness: PublicTrackHarness,
    payload: dict[str, object],
) -> None:
    response = public_track_harness.post(
        payload=payload,
        headers=_headers(),
    )

    assert response.status_code == 422
    assert response.json() == {"ok": False}


def test_order_number_is_trimmed_before_length_check_and_lookup(
    public_track_harness: PublicTrackHarness,
) -> None:
    order_number = "x" * 64
    response = public_track_harness.post(
        payload={"order_numbers": [f"  {order_number}  "]},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["order_number"] == order_number


def test_blank_order_number_is_trimmed_and_returns_unknown(
    public_track_harness: PublicTrackHarness,
) -> None:
    response = public_track_harness.post(
        payload={"order_numbers": ["   "]},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["results"] == [
        {
            "order_number": "",
            "state": "unknown",
            "tracking_number": None,
            "carrier_code": None,
            "tracking_status": None,
            "last_update": None,
            "events": [],
        }
    ]


def test_public_track_route_is_mounted_once_on_main_app() -> None:
    routes = [
        route
        for route in main_app.routes
        if getattr(route, "path", None) == TRACK_PATH
    ]

    assert len(routes) == 1
    assert routes[0].methods == {"POST"}


def test_authenticated_oversized_body_is_rejected_before_buffering(
    public_track_harness: PublicTrackHarness,
) -> None:
    oversized = b'{' + (b'"padding":' + b'"' + b'x' * 33_000 + b'"') + b'}'
    response = public_track_harness.post_content(
        content=oversized,
        headers={**_headers(), "Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json() == {"ok": False}


def test_authenticated_malformed_json_consumes_global_limit(
    public_track_harness: PublicTrackHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logistics, "TRACK_PUBLIC_MINUTE_LIMIT", 1)
    malformed = public_track_harness.post_content(
        content=b"{not-json",
        headers={**_headers(), "Content-Type": "application/json"},
    )
    limited = public_track_harness.post(
        payload={"order_numbers": ["NEXT"]},
        headers=_headers(),
    )

    assert malformed.status_code == 422
    assert limited.status_code == 429


def test_global_rate_limit_returns_429_across_different_ip_headers(
    public_track_harness: PublicTrackHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logistics, "TRACK_PUBLIC_MINUTE_LIMIT", 1)

    first = public_track_harness.post(
        payload={"order_numbers": ["ONE"]},
        headers={**_headers(), "X-Forwarded-For-Origin": "203.0.113.10"},
    )
    limited = public_track_harness.post(
        payload={"order_numbers": ["TWO"]},
        headers={**_headers(), "X-Forwarded-For-Origin": "198.51.100.20"},
    )

    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.json() == {"ok": False}


def test_global_rate_limit_allows_600_and_rejects_601st(
    public_track_harness: PublicTrackHarness,
) -> None:
    started_at = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    with public_track_harness.sessions() as db:
        for _ in range(600):
            assert logistics.register_track_public_rate_limit(
                db,
                now=started_at,
            )
            db.commit()
        assert not logistics.register_track_public_rate_limit(
            db,
            now=started_at,
        )
        db.commit()
        assert logistics.register_track_public_rate_limit(
            db,
            now=started_at + timedelta(seconds=61),
        )


def test_one_lookup_failure_degrades_only_that_result(
    public_track_harness: PublicTrackHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_order(
        public_track_harness,
        woo_order_id=7001,
        order_number="GOOD-1",
        tracking_number="TRACK-GOOD-1",
        tracking_status="registered",
    )
    _seed_order(
        public_track_harness,
        woo_order_id=7002,
        order_number="GOOD-2",
        tracking_number="TRACK-GOOD-2",
        tracking_status="delivered",
    )
    original_lookup = w_router._lookup_public_track_result

    def flaky_lookup(db: Session, order_number: str):
        if order_number == "BROKEN":
            db.execute(text("SELECT * FROM intentionally_missing_table"))
        return original_lookup(db, order_number)

    monkeypatch.setattr(w_router, "_lookup_public_track_result", flaky_lookup)
    response = public_track_harness.post(
        payload={"order_numbers": ["GOOD-1", "BROKEN", "GOOD-2"]},
        headers=_headers(),
    )

    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert [item["state"] for item in results] == [
        "tracked",
        "unknown",
        "tracked",
    ]
    assert results[0]["tracking_status"] == "not_found"
    assert results[1]["order_number"] == "BROKEN"
    assert results[2]["tracking_status"] == "delivered"
