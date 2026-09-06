"""贸易公司主页：引导、权限门、外组织不可见、降级、SSE 首帧。"""

from __future__ import annotations

import asyncio
import importlib
import dataclasses
import json
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import OperationalError

from backend.app.core.config import Settings
from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.permission import UserPermissionAssignment
from backend.app.models.user import User
from backend.app.modules.b2b.outreach.models import B2BEmailDraft
from backend.app.modules.b2b.outreach.suppression import B2BSuppression
from backend.app.modules.b2b.prospects.models import B2BProspect
from backend.app.modules.cs_series.models import (
    CSMessage,
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_SCOPE_MODE,
    TARGET_ORGANIZATION_NAME,
)
from backend.app.modules.geo_series.content.models import (
    GeoContentCluster,
    GeoContentItem,
    GeoPublishJob,
)
from backend.app.modules.h_series.sitehealth.models import HHealthRun
from backend.app.modules.home import stream as home_stream_module
from backend.app.modules.home.context import resolve_home_access
from backend.app.modules.home.registry import STORE_CARDS, load_cards
from backend.app.modules.home.router import home_stream

# `home/__init__.py` 把 router 这个名字导出成 APIRouter 对象，from-import 拿不到模块本体
home_router_module = importlib.import_module("backend.app.modules.home.router")
from backend.app.modules.w_series.shipping.models import WOrder
from backend.app.modules.w_series.traffic.models import WTrafficDaily, WTrafficHourly
from backend.app.services.approval_service import ApprovalService
from backend.app.services.data_isolation import (
    OrgDataIsolationUserContext,
    org_data_isolation_context,
    without_org_data_isolation,
)
from backend.app.services.permission_service import upsert_permission_registry
from tests.fixtures.organization_fixtures import DEFAULT_TEST_ORG_DB_ID

pytestmark = pytest.mark.integration

ALL_CARD_IDS = [
    "site-traffic",
    "site-health",
    "cs-inbox",
    "w-orders",
    "geo-todo",
    "seo-todo",
    "b2b-drafts",
    "sm-todo",
    "approvals",
]
OTHER_STORE_ORG_ID = "org_33333333333333333333333333333333"
FACTORY_ORG_ID = "org_44444444444444444444444444444444"


def _purge_business_rows() -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        for model in (
            GeoPublishJob,
            GeoContentItem,
            GeoContentCluster,
            WOrder,
            B2BEmailDraft,
            B2BSuppression,
            B2BProspect,
            WTrafficDaily,
            WTrafficHourly,
            HHealthRun,
        ):
            db.execute(delete(model))
        db.execute(text("DELETE FROM worker_heartbeats WHERE worker_name = 'w-traffic'"))
        db.commit()


@pytest.fixture(autouse=True)
def _clean_business_rows() -> Iterator[None]:
    _purge_business_rows()
    yield
    _purge_business_rows()


@pytest.fixture
def home_client(owner_client: TestClient) -> TestClient:
    with SessionLocal() as db:
        upsert_permission_registry(db)
    return owner_client


def _seed_cs(org_id: str, *, status: str = "new", channel: str = "retail") -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        db.add(
            CSMessage(
                org_id=org_id,
                workspace_key=org_id,
                business_context=DEFAULT_BUSINESS_CONTEXT,
                scope_mode=DEFAULT_SCOPE_MODE,
                organization_name=(
                    TARGET_ORGANIZATION_NAME if org_id == DEFAULT_TEST_ORG_DB_ID else "外组织"
                ),
                channel=channel,
                name=f"{channel}-{status}",
                email=f"{channel}.{status}@example.com",
                message=f"seeded {channel} {status}",
                client_ip="198.51.100.10",
                status=status,
            )
        )
        db.commit()


def _seed_geo(workspace_key: str, *, review_status: str = "pending") -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        cluster = GeoContentCluster(
            workspace_key=workspace_key,
            title=f"cluster {workspace_key[-4:]}",
            status="ready",
        )
        db.add(cluster)
        db.flush()
        db.add(
            GeoContentItem(
                workspace_key=workspace_key,
                cluster_id=cluster.id,
                item_type="hub",
                title=f"item {workspace_key[-4:]}",
                review_status=review_status,
                generation_status="generated",
            )
        )
        db.commit()


def _seed_order(*, woo_status: str = "processing", tracking_status: str = "none") -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        db.add(
            WOrder(
                woo_order_id=int(uuid4().int % 1_000_000_000),
                order_number=f"BY-{uuid4().hex[:6]}",
                woo_status=woo_status,
                customer_name="Emily",
                country="US",
                tracking_status=tracking_status,
            )
        )
        db.commit()


def _seed_b2b_draft(*, status: str = "draft") -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        prospect = B2BProspect(
            dedupe_key=f"dk-{uuid4().hex}",
            store_name="Ridge Outfitters",
            country="US",
            store_type="outdoor",
            language="en",
        )
        db.add(prospect)
        db.flush()
        db.add(
            B2BEmailDraft(
                prospect_id=prospect.id,
                kind="first_touch",
                language="en",
                to_email="buyer@example.com",
                subject="Camping shower wholesale",
                body="Hello",
                status=status,
            )
        )
        db.commit()


def _create_org_user(
    *,
    org_id: str,
    org_name: str,
    org_type: str,
    role: str,
    membership_role: str,
    username: str,
    permission_keys: tuple[str, ...] = (),
) -> tuple[str, str]:
    password = f"{username}-password"
    with without_org_data_isolation(), SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
            must_change_password=False,
        )
        db.add(user)
        db.flush()
        if db.get(OrganizationRecord, org_id) is None:
            db.add(
                OrganizationRecord(
                    org_id=org_id,
                    org_name=org_name,
                    org_type=org_type,
                    owner_user_id=str(user.id),
                    status="active",
                    metadata_json={},
                )
            )
            db.flush()
        db.add(
            OrgMembershipRecord(
                membership_id=f"mem_{user.id:032x}",
                user_id=str(user.id),
                org_id=org_id,
                role=membership_role,
                status="active",
            )
        )
        for key in permission_keys:
            db.add(
                UserPermissionAssignment(
                    user_id=user.id,
                    permission_key=key,
                    scope_type="organization",
                    scope_key=org_id,
                    reason="home dashboard test",
                    is_enabled=True,
                )
            )
        db.commit()
    return username, password


def _login(username: str, password: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/public/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return client


def _card_ids(payload: dict) -> list[str]:
    return [card["card_id"] for card in payload["cards"]]


def _card(payload: dict, card_id: str) -> dict:
    return next(card for card in payload["cards"] if card["card_id"] == card_id)


# ---------------------------------------------------------------- 引导


def test_bootstrap_store_owner_sees_all_cards_in_design_order(home_client: TestClient) -> None:
    response = home_client.get("/api/app/dashboard/home")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["org_type"] == "store"
    assert payload["org_id"] == DEFAULT_TEST_ORG_DB_ID
    assert _card_ids(payload) == ALL_CARD_IDS
    assert payload["poll_seconds"] == 3.0
    traffic = _card(payload, "site-traffic")
    assert traffic["module_key"] is None
    assert traffic["extra"]["collector_stale"] is True
    assert len(traffic["extra"]["days"]) == 7


def test_bootstrap_factory_org_gets_factory_cards(home_client: TestClient) -> None:
    """制造公司有自己的皮（详见 test_home_factory.py）；这里只守：不是贸易公司的卡、流量端点仍 403。"""
    username, password = _create_org_user(
        org_id=FACTORY_ORG_ID,
        org_name="测试制造公司",
        org_type="factory",
        role="super_admin",
        membership_role="admin",
        username="home_factory_admin",
    )
    client = _login(username, password)

    response = client.get("/api/app/dashboard/home")
    stream = client.get("/api/app/dashboard/home/stream")
    traffic = client.get("/api/app/dashboard/home/traffic")

    assert response.status_code == 200, response.text
    assert response.json()["org_type"] == "factory"
    factory_ids = [card["card_id"] for card in response.json()["cards"]]
    assert factory_ids and not set(factory_ids) & {"site-traffic", "cs-inbox", "w-orders", "b2b-drafts"}
    assert stream.status_code == 200
    assert traffic.status_code == 403


def test_unknown_card_is_404(home_client: TestClient) -> None:
    assert home_client.get("/api/app/dashboard/home/cards/nope").status_code == 404


# ---------------------------------------------------------------- 外组织不可见


def test_cs_card_counts_only_current_org_rows(home_client: TestClient) -> None:
    _seed_cs(DEFAULT_TEST_ORG_DB_ID)
    _seed_cs(DEFAULT_TEST_ORG_DB_ID, channel="wholesale")
    _seed_cs(DEFAULT_TEST_ORG_DB_ID, status="resolved")
    _seed_cs(OTHER_STORE_ORG_ID)

    card = home_client.get("/api/app/dashboard/home/cards/cs-inbox").json()

    assert card["count"] == 2
    assert card["extra"] == {"retail": 1, "wholesale": 1}
    assert {item["title"] for item in card["items"]} == {"retail-new · 零售", "wholesale-new · 批发"}


def test_geo_card_is_workspace_scoped(home_client: TestClient) -> None:
    _seed_geo(DEFAULT_TEST_ORG_DB_ID)
    _seed_geo(DEFAULT_TEST_ORG_DB_ID, review_status="approved")
    _seed_geo(OTHER_STORE_ORG_ID)

    card = home_client.get("/api/app/dashboard/home/cards/geo-todo").json()

    assert card["extra"]["pending_review"] == 1
    assert card["extra"]["unpublished"] == 1
    assert card["count"] == 2
    assert len(card["items"]) == 1


def test_target_org_only_cards_are_absent_for_another_store_org(home_client: TestClient) -> None:
    _seed_order()
    _seed_b2b_draft()
    _seed_cs(DEFAULT_TEST_ORG_DB_ID)
    username, password = _create_org_user(
        org_id=OTHER_STORE_ORG_ID,
        org_name="另一家贸易公司",
        org_type="store",
        role="super_admin",
        membership_role="admin",
        username="home_other_store_admin",
    )
    client = _login(username, password)

    payload = client.get("/api/app/dashboard/home").json()
    w_card = client.get("/api/app/dashboard/home/cards/w-orders")
    traffic = client.get("/api/app/dashboard/home/traffic")

    assert payload["org_type"] == "store"
    assert _card_ids(payload) == ["geo-todo", "seo-todo", "sm-todo", "approvals"]
    assert w_card.status_code == 403
    assert traffic.status_code == 403
    # 本组织照常看得到
    own = home_client.get("/api/app/dashboard/home").json()
    assert _card(own, "w-orders")["count"] == 1
    assert _card(own, "b2b-drafts")["count"] == 1
    assert _card(own, "cs-inbox")["count"] == 1


# ---------------------------------------------------------------- 权限门


def test_module_card_absent_without_permission_and_present_with_it(home_client: TestClient) -> None:
    username, password = _create_org_user(
        org_id=DEFAULT_TEST_ORG_DB_ID,
        org_name=TARGET_ORGANIZATION_NAME,
        org_type="store",
        role="operator",
        membership_role="member",
        username="home_member_no_cs",
    )
    client = _login(username, password)
    payload = client.get("/api/app/dashboard/home").json()
    assert "cs-inbox" not in _card_ids(payload)
    assert "site-traffic" in _card_ids(payload)
    assert client.get("/api/app/dashboard/home/cards/cs-inbox").status_code == 403

    username2, password2 = _create_org_user(
        org_id=DEFAULT_TEST_ORG_DB_ID,
        org_name=TARGET_ORGANIZATION_NAME,
        org_type="store",
        role="operator",
        membership_role="member",
        username="home_member_with_cs",
        permission_keys=("cs.customer_service.read",),
    )
    client2 = _login(username2, password2)
    payload2 = client2.get("/api/app/dashboard/home").json()
    assert "cs-inbox" in _card_ids(payload2)
    # 治理读权与旧主页 `_can_read(GOVERNANCE, read)` 同一规则；普通成员也能看列表，
    # 这里只断言卡在、动作里永远有「已读」。
    approvals = _card(payload2, "approvals")
    assert "read" in approvals["actions"]
    assert approvals["extra"]["unread"] == 0


# ---------------------------------------------------------------- 降级与只读


def test_approvals_card_degrades_without_breaking_other_cards(
    home_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(self, **_kwargs):  # noqa: ANN001
        raise OperationalError("SELECT 1", {}, Exception("canceling statement due to statement timeout"))

    monkeypatch.setattr(ApprovalService, "list_approval_page", _boom)
    _seed_cs(DEFAULT_TEST_ORG_DB_ID)

    payload = home_client.get("/api/app/dashboard/home").json()

    approvals = _card(payload, "approvals")
    assert approvals["extra"]["approvals_degraded"] is True
    assert approvals["severity"] == "warn"
    assert approvals["count"] == 0
    assert _card(payload, "cs-inbox")["count"] == 1


def test_loaders_never_commit_or_flush(home_client: TestClient) -> None:
    _seed_cs(DEFAULT_TEST_ORG_DB_ID)
    _seed_geo(DEFAULT_TEST_ORG_DB_ID)
    _seed_order()
    _seed_b2b_draft()
    with without_org_data_isolation(), SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "f10_api_owner"))
        assert user is not None
        access = resolve_home_access(db, user=user, org_id=DEFAULT_TEST_ORG_DB_ID)
        assert access is not None and access.is_store and access.is_target_org
        writes: list[str] = []
        original_commit, original_flush = db.commit, db.flush
        db.commit = lambda: writes.append("commit") or original_commit()  # type: ignore[method-assign]
        db.flush = lambda *a, **k: writes.append("flush") or original_flush(*a, **k)  # type: ignore[method-assign]

        isolation = OrgDataIsolationUserContext(
            org_id=DEFAULT_TEST_ORG_DB_ID, user_id=str(user.id), role=str(user.role),
            source="test", strict=False,
        )
        with org_data_isolation_context(isolation):
            cards = load_cards(db, access=access, user=user, specs=STORE_CARDS)

        assert [card.card_id for card in cards] == ALL_CARD_IDS
        assert not any(card.extra.get("degraded") for card in cards)
        assert writes == []


# ---------------------------------------------------------------- SSE


def _raw_stream_request() -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/api/app/dashboard/home/stream",
            "raw_path": b"/api/app/dashboard/home/stream",
            "query_string": b"",
            "headers": [
                (b"accept", b"text/event-stream"),
                (b"x-session-token", b"test-home-session"),
            ],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 443),
        },
        receive,
    )
    request.state.org_id = DEFAULT_TEST_ORG_DB_ID
    return request


def test_stream_first_frames_push_only_changed_cards(
    home_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fast_settings = Settings(home_stream_poll_seconds=1.0, home_stream_lifetime_seconds=10)
    fast_settings.home_stream_poll_seconds = 0.01
    monkeypatch.setattr(home_stream_module, "get_settings", lambda: fast_settings)
    # 流的卡片集由路由的 cards_for 决定；把节流清零打在那里，否则 3 秒内不重算
    monkeypatch.setattr(
        home_router_module,
        "cards_for",
        lambda access: tuple(dataclasses.replace(spec, min_refresh_seconds=0.0) for spec in STORE_CARDS),
    )

    with without_org_data_isolation(), SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "f10_api_owner"))
        assert user is not None

        @contextmanager
        def live_session():
            yield db

        monkeypatch.setattr(home_stream_module, "managed_read_session", live_session)
        monkeypatch.setattr(
            home_stream_module,
            "validate_session",
            lambda *_a, **_k: SimpleNamespace(user=user),
        )

        async def run() -> tuple[StreamingResponse, list[str]]:
            response = home_stream(request=_raw_stream_request(), db=db, user=user)
            assert isinstance(response, StreamingResponse)
            iterator = response.body_iterator
            frames = [await anext(iterator)]           # retry
            frames.append(await anext(iterator))       # nothing changed → keep-alive
            _seed_cs(DEFAULT_TEST_ORG_DB_ID)
            db.expire_all()
            frames.append(await anext(iterator))       # cs-inbox changed
            frames.append(await anext(iterator))       # settled again
            await iterator.aclose()
            return response, frames

        response, frames = asyncio.run(run())

    assert frames[0] == "retry: 2000\n\n"
    assert frames[1] == ": keep-alive\n\n"
    assert frames[2].startswith("event: card\ndata: ")
    card = json.loads(frames[2].split("data: ", 1)[1].strip())
    assert card["card_id"] == "cs-inbox"
    assert card["count"] == 1
    assert frames[3] == ": keep-alive\n\n"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-cache, no-transform"


def test_stream_closes_when_session_user_changes(
    home_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fast_settings = Settings(home_stream_poll_seconds=1.0, home_stream_lifetime_seconds=10)
    fast_settings.home_stream_poll_seconds = 0.01
    monkeypatch.setattr(home_stream_module, "get_settings", lambda: fast_settings)

    with without_org_data_isolation(), SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "f10_api_owner"))
        assert user is not None
        other = SimpleNamespace(id=int(user.id) + 999, role="owner")

        @contextmanager
        def live_session():
            yield db

        monkeypatch.setattr(home_stream_module, "managed_read_session", live_session)
        monkeypatch.setattr(
            home_stream_module,
            "validate_session",
            lambda *_a, **_k: SimpleNamespace(user=other),
        )

        async def run() -> list[str]:
            response = home_stream(request=_raw_stream_request(), db=db, user=user)
            iterator = response.body_iterator
            frames = [await anext(iterator)]
            with pytest.raises(StopAsyncIteration):
                await anext(iterator)
            return frames

        frames = asyncio.run(run())

    assert frames == ["retry: 2000\n\n"]
