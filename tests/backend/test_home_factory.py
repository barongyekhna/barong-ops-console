"""制造公司主页：五张卡、角色硬门、缺料推算、工厂时区、霓旌心跳、只读。"""

from __future__ import annotations

import asyncio
import importlib
import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from backend.app.core.config import Settings
from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models.operation_log import OperationLog
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.permission import UserPermissionAssignment
from backend.app.models.user import User
from backend.app.modules.home import stream as home_stream_module
from backend.app.modules.home.context import resolve_home_access
from backend.app.modules.home.factory_registry import FACTORY_CARDS
from backend.app.modules.home.registry import load_cards
from backend.app.modules.home.router import home_stream

# `home/__init__.py` 把 router 这个名字导出成 APIRouter 对象，from-import 拿不到模块本体
home_router_module = importlib.import_module("backend.app.modules.home.router")
from backend.app.modules.m_series.home_card import factory_today_start
from backend.app.modules.m_series.inventory import schemas as S
from backend.app.modules.m_series.inventory import service
from backend.app.modules.m_series.inventory.models import (
    MfgBomLine,
    MfgDocCounter,
    MfgDocument,
    MfgItem,
    MfgMovement,
)
from backend.app.services.data_isolation import (
    OrgDataIsolationUserContext,
    org_data_isolation_context,
    without_org_data_isolation,
)
from backend.app.services.permission_service import upsert_permission_registry

pytestmark = pytest.mark.integration

FACTORY_ORG_ID = "org_55555555555555555555555555555555"
FACTORY_CARD_IDS = ["mfg-stock", "mfg-capacity", "mfg-docs", "nijing", "approvals"]
D = Decimal


def _purge() -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        for model in (MfgMovement, MfgDocument, MfgBomLine, MfgItem, MfgDocCounter):
            db.execute(delete(model))
        db.execute(delete(OperationLog).where(OperationLog.actor_id == "mfg.nijing"))
        db.execute(text("DELETE FROM worker_heartbeats WHERE worker_name = 'nijing-worker'"))
        db.commit()


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    _purge()
    yield
    _purge()


def _create_factory_user(
    *, role: str, username: str, permission_keys: tuple[str, ...] = ()
) -> tuple[str, str]:
    password = f"{username}-password"
    with without_org_data_isolation(), SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
            must_change_password=False,
            organization_id=FACTORY_ORG_ID,
        )
        db.add(user)
        db.flush()
        if db.get(OrganizationRecord, FACTORY_ORG_ID) is None:
            db.add(
                OrganizationRecord(
                    org_id=FACTORY_ORG_ID,
                    org_name="测试制造公司",
                    org_type="factory",
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
                org_id=FACTORY_ORG_ID,
                role="admin" if role == "super_admin" else "member",
                status="active",
            )
        )
        for key in permission_keys:
            db.add(
                UserPermissionAssignment(
                    user_id=user.id,
                    permission_key=key,
                    scope_type="organization",
                    scope_key=FACTORY_ORG_ID,
                    reason="factory home test",
                    is_enabled=True,
                )
            )
        db.commit()
    return username, password


def _login(username: str, password: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/api/public/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def factory_admin(owner_client: TestClient) -> TestClient:
    """owner_client 只是为了拿到干净库 + 贸易组织；返回的是制造公司超管的客户端。"""
    with SessionLocal() as db:
        upsert_permission_registry(db)
    username, password = _create_factory_user(role="super_admin", username="home_factory_super")
    return _login(username, password)


def _ctx() -> service.FactoryContext:
    with SessionLocal() as db:
        return service.resolve_factory_context(db)


def _owner_user() -> User:
    user = User(username="mfg_owner", password_hash="x", role="owner", is_active=True)
    user.id = 1
    return user


def _table_setup() -> dict[str, MfgItem]:
    """桌子 = 1 桌面 + 4 桌腿 + 1 横梁；10 张装 1 箱。入库 1000/800/500/100。"""
    with SessionLocal() as db:
        ctx = service.resolve_factory_context(db)

        def item(kind: str, code: str, unit: str = "个") -> MfgItem:
            return service.create_item(db, ctx, S.ItemCreate(kind=kind, code=code, name=code, unit=unit))

        top, leg, beam, box = item("part", "TOP"), item("part", "LEG", "条"), item("part", "BEAM", "根"), item("part", "BOX")
        table = item("product", "TABLE", "套")
        service.replace_bom(
            db,
            ctx,
            table.id,
            S.BomReplace(
                lines=[
                    S.BomLineInput(part_id=top.id, mode="per_unit", qty=D("1")),
                    S.BomLineInput(part_id=leg.id, mode="per_unit", qty=D("4")),
                    S.BomLineInput(part_id=beam.id, mode="per_unit", qty=D("1")),
                    S.BomLineInput(part_id=box.id, mode="per_carton", qty=D("10")),
                ]
            ),
        )
        service.receipt(
            db,
            ctx,
            user=_owner_user(),
            payload=S.ReceiptCreate(
                lines=[
                    S.ReceiptLine(item_id=top.id, qty=D("1000")),
                    S.ReceiptLine(item_id=leg.id, qty=D("800")),
                    S.ReceiptLine(item_id=beam.id, qty=D("500")),
                    S.ReceiptLine(item_id=box.id, qty=D("100")),
                ]
            ),
        )
        for row in (top, leg, beam, box, table):
            db.expunge(row)
        return {"top": top, "leg": leg, "beam": beam, "box": box, "table": table}


def _card_ids(payload: dict) -> list[str]:
    return [card["card_id"] for card in payload["cards"]]


def _card(payload: dict, card_id: str) -> dict:
    return next(card for card in payload["cards"] if card["card_id"] == card_id)


# ---------------------------------------------------------------- 引导与门


def test_factory_super_admin_gets_factory_cards(factory_admin: TestClient) -> None:
    payload = factory_admin.get("/api/app/dashboard/home").json()

    assert payload["org_type"] == "factory"
    assert payload["org_id"] == FACTORY_ORG_ID
    assert _card_ids(payload) == FACTORY_CARD_IDS
    assert factory_admin.get("/api/app/dashboard/home/cards/mfg-stock").status_code == 200
    assert factory_admin.get("/api/app/dashboard/home/traffic").status_code == 403
    assert factory_admin.get("/api/app/dashboard/home/cards/site-traffic").status_code == 404


def test_factory_member_without_role_gets_only_agent_and_governance(owner_client: TestClient) -> None:
    with SessionLocal() as db:
        upsert_permission_registry(db)
    _create_factory_user(role="super_admin", username="home_factory_super_seed")  # 建组织
    username, password = _create_factory_user(
        role="operator", username="home_factory_member", permission_keys=("mfg.inventory.read",)
    )
    client = _login(username, password)

    payload = client.get("/api/app/dashboard/home").json()

    # 权限码给了也没用：M 模块的门是角色硬门，主页照同一条规则
    assert _card_ids(payload) == ["nijing", "approvals"]
    assert client.get("/api/app/dashboard/home/cards/mfg-stock").status_code == 404


def test_store_owner_sees_no_factory_cards(factory_admin: TestClient, owner_client: TestClient) -> None:
    payload = owner_client.get("/api/app/dashboard/home").json()

    assert payload["org_type"] == "store"
    assert not set(_card_ids(payload)) & {"mfg-stock", "mfg-capacity", "mfg-docs", "nijing"}
    assert owner_client.get("/api/app/dashboard/home/cards/mfg-stock").status_code == 404


# ---------------------------------------------------------------- 三张 mfg 卡


def test_stock_and_capacity_cards_derive_shortage_from_bom(factory_admin: TestClient) -> None:
    items = _table_setup()

    payload = factory_admin.get("/api/app/dashboard/home").json()
    stock = _card(payload, "mfg-stock")
    capacity = _card(payload, "mfg-capacity")

    assert stock["extra"]["parts_total"] == 4
    assert stock["extra"]["products_total"] == 1
    assert stock["extra"]["zero_count"] == 1  # TABLE 还没生产过
    assert stock["extra"]["zero"][0]["code"] == "TABLE"
    assert stock["count"] == 1 and stock["severity"] == "warn"

    table = capacity["extra"]["products"][0]
    # min(1000/1, 800/4, 500/1, 100 箱 × 10) = 200，卡在桌腿
    assert table["code"] == "TABLE"
    assert table["max_producible"] == "200"
    assert table["blocker_code"] == "LEG"
    assert capacity["count"] == 0 and capacity["severity"] == "ok"

    # 把桌腿清零 → 生产能力归零、卡片黄
    with SessionLocal() as db:
        ctx = service.resolve_factory_context(db)
        service.adjustment(
            db,
            ctx,
            user=_owner_user(),
            payload=S.AdjustmentCreate(item_id=items["leg"].id, qty_delta=D("-800"), reason="盘点"),
        )
    capacity = factory_admin.get("/api/app/dashboard/home/cards/mfg-capacity").json()
    assert capacity["count"] == 1 and capacity["severity"] == "warn"
    assert capacity["items"][0]["title"] == "TABLE 最多可产 0 套"
    assert "卡在 LEG" in capacity["items"][0]["subtitle"]


def test_docs_card_counts_today_in_factory_timezone(factory_admin: TestClient) -> None:
    _table_setup()

    card = factory_admin.get("/api/app/dashboard/home/cards/mfg-docs").json()

    assert card["extra"]["today"]["receipt"] == 1
    assert card["extra"]["today_total"] == 1
    assert card["count"] == 1
    assert card["extra"]["recent"][0]["doc_no"].startswith("RC-")
    assert card["extra"]["tz"].startswith("工厂时间")
    assert card["items"][0]["title"].endswith("· 入库")


def test_factory_today_start_uses_shanghai_day() -> None:
    # UTC 17:00 = 上海次日 01:00，所以「今天」从上海次日 00:00 起
    start = factory_today_start(datetime(2026, 9, 5, 17, 0, tzinfo=UTC))
    assert start.isoformat() == "2026-09-06T00:00:00+08:00"


# ---------------------------------------------------------------- 霓旌


def test_nijing_card_reads_heartbeat_and_operation_logs(factory_admin: TestClient) -> None:
    before = factory_admin.get("/api/app/dashboard/home/cards/nijing").json()
    assert before["severity"] == "error"
    assert before["extra"]["heartbeat"]["stale"] is True

    with without_org_data_isolation(), SessionLocal() as db:
        db.execute(
            text(
                "INSERT INTO worker_heartbeats (worker_name, module_key, last_success_at, last_attempt_at, "
                "consecutive_failures, expected_interval_seconds, updated_at) "
                "VALUES ('nijing-worker', 'agent.nijing', now(), now(), 0, 900, now())"
            )
        )
        for index, (action, result) in enumerate(
            (("agent.mfg.receipt", "success"), ("agent.mfg.denied", "denied"), ("agent.mfg.brain", "success"))
        ):
            db.add(
                OperationLog(
                    org_id=FACTORY_ORG_ID,
                    operation_id=f"op-nijing-{index}",
                    actor_type="agent",
                    actor_id="mfg.nijing",
                    action=action,
                    target_type="mfg_document",
                    target_id=f"RC-00000{index}",
                    result=result,
                )
            )
        db.commit()

    card = factory_admin.get("/api/app/dashboard/home/cards/nijing").json()

    assert card["extra"]["heartbeat"]["stale"] is False
    assert card["extra"]["today"] == {"success": 1, "failure": 0, "rejected": 0, "denied": 1}
    assert card["count"] == 1
    assert card["severity"] == "warn"
    titles = [item["title"] for item in card["items"]]
    assert titles == ["被门禁拦下 · 无权", "入库 · 成功"]  # brain 不算办事


# ---------------------------------------------------------------- 只读 + 流


def test_factory_loaders_never_commit_or_flush(factory_admin: TestClient) -> None:
    _table_setup()
    with without_org_data_isolation(), SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "home_factory_super"))
        assert user is not None
        access = resolve_home_access(db, user=user, org_id=FACTORY_ORG_ID)
        assert access is not None and access.is_factory
        writes: list[str] = []
        original_commit, original_flush = db.commit, db.flush
        db.commit = lambda: writes.append("commit") or original_commit()  # type: ignore[method-assign]
        db.flush = lambda *a, **k: writes.append("flush") or original_flush(*a, **k)  # type: ignore[method-assign]
        isolation = OrgDataIsolationUserContext(
            org_id=FACTORY_ORG_ID, user_id=str(user.id), role=str(user.role), source="test", strict=False
        )
        with org_data_isolation_context(isolation):
            cards = load_cards(db, access=access, user=user, specs=FACTORY_CARDS)

        assert [card.card_id for card in cards] == FACTORY_CARD_IDS
        assert not any(card.extra.get("degraded") for card in cards)
        assert writes == []


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
            "headers": [(b"accept", b"text/event-stream"), (b"x-session-token", b"test-factory-session")],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 443),
        },
        receive,
    )
    request.state.org_id = FACTORY_ORG_ID
    return request


def test_factory_stream_opens_and_pushes_doc_changes(
    factory_admin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fast_settings = Settings(home_stream_poll_seconds=1.0, home_stream_lifetime_seconds=10)
    fast_settings.home_stream_poll_seconds = 0.01
    monkeypatch.setattr(home_stream_module, "get_settings", lambda: fast_settings)
    # 流的卡片集由路由的 cards_for 决定；把节流清零打在那里，否则 3 秒内不重算
    monkeypatch.setattr(
        home_router_module,
        "cards_for",
        lambda access: tuple(dataclasses.replace(spec, min_refresh_seconds=0.0) for spec in FACTORY_CARDS),
    )
    _table_setup()

    with without_org_data_isolation(), SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "home_factory_super"))
        assert user is not None

        @contextmanager
        def live_session():
            yield db

        monkeypatch.setattr(home_stream_module, "managed_read_session", live_session)
        monkeypatch.setattr(home_stream_module, "validate_session", lambda *_a, **_k: SimpleNamespace(user=user))

        async def run() -> list[str]:
            response = home_stream(request=_raw_stream_request(), db=db, user=user)
            assert isinstance(response, StreamingResponse)
            iterator = response.body_iterator
            frames = [await anext(iterator), await anext(iterator)]
            ctx = service.resolve_factory_context(db)
            leg = db.scalar(select(MfgItem).where(MfgItem.code == "LEG"))
            service.receipt(db, ctx, user=_owner_user(), payload=S.ReceiptCreate(lines=[S.ReceiptLine(item_id=leg.id, qty=D("1"))]))
            db.expire_all()
            # 一张入库单同时改了生产能力卡（桌腿 800→801）和今日单据卡，按注册表顺序各推一帧
            for _ in range(4):
                frames.append(await anext(iterator))
                if '"card_id":"mfg-docs"' in frames[-1]:
                    break
            await iterator.aclose()
            return frames

        frames = asyncio.run(run())

    assert frames[0] == "retry: 2000\n\n"
    assert frames[1] == ": keep-alive\n\n"
    pushed = [frame for frame in frames[2:] if frame.startswith("event: card\ndata: ")]
    assert pushed and all("keep-alive" not in frame for frame in frames[2:])
    assert '"card_id":"mfg-docs"' in pushed[-1]
    assert any('"card_id":"mfg-capacity"' in frame for frame in pushed)
