"""W-S product-source CRUD, enrichment, batching, and permission tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import quote
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal, engine as db_engine
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.user import User
from backend.app.modules.w_series.shipping.models import WOrder, WSyncJob
from tests.backend.conftest import DEFAULT_TEST_ORG_DB_ID
from backend.app.services.permission_service import (
    grant_permission,
    upsert_permission_registry,
)


pytestmark = pytest.mark.integration

_SOURCE_URL = "https://detail.1688.com/offer/123456789.html"


def _clean_w_source_rows() -> None:
    with SessionLocal() as db:
        db.execute(delete(WSyncJob))
        db.execute(delete(WOrder))
        db.execute(text("DELETE FROM w_product_sources"))
        db.commit()


@pytest.fixture
def sources_client(owner_client: TestClient) -> TestClient:
    _clean_w_source_rows()
    yield owner_client
    _clean_w_source_rows()


def _source_payload(
    *,
    supplier_name: str = "测试供应商",
    unit_cost: str = "12.34",
    moq: int = 5,
) -> dict[str, object]:
    return {
        "source_url": _SOURCE_URL,
        "supplier_name": supplier_name,
        "unit_cost": unit_cost,
        "currency": "CNY",
        "moq": moq,
        "notes": "要选蓝色款",
    }


def _put_source(
    client: TestClient,
    sku: str,
    *,
    payload: dict[str, object] | None = None,
) -> object:
    response = client.put(
        f"/api/app/w/sources/{quote(sku, safe='')}",
        json=payload or _source_payload(),
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()


def _new_order(items: list[dict[str, object]]) -> UUID:
    order_id = uuid4()
    woo_order_id = 800_000_000 + order_id.int % 100_000_000
    with SessionLocal() as db:
        db.add(
            WOrder(
                id=order_id,
                woo_order_id=woo_order_id,
                order_number=f"SOURCE-TEST-{order_id.hex[:12]}",
                woo_status="processing",
                customer_name="货源测试客户",
                country="US",
                total=Decimal("29.99"),
                currency="USD",
                items_json=items,
                placed_at=datetime(2026, 7, 21, 1, 2, tzinfo=UTC),
            )
        )
        db.commit()
    return order_id


def _response_items_for_order(response: object, order_id: UUID) -> list[dict]:
    assert hasattr(response, "status_code")
    assert response.status_code == 200, response.text
    order = next(
        item
        for item in response.json()["orders"]
        if item["id"] == str(order_id)
    )
    return order["items_json"]


def test_source_upsert_normalizes_sku_and_updates_one_row(
    sources_client: TestClient,
) -> None:
    _put_source(
        sources_client,
        " igl-001 ",
        payload=_source_payload(supplier_name="初始供应商"),
    )
    updated = _put_source(
        sources_client,
        "IGL-001",
        payload=_source_payload(supplier_name="更新供应商"),
    )

    assert updated["sku"] == "IGL-001"
    assert updated["supplier_name"] == "更新供应商"
    with SessionLocal() as db:
        rows = list(
            db.execute(
                text(
                    "SELECT sku, supplier_name FROM w_product_sources "
                    "WHERE sku = 'IGL-001'"
                )
            ).mappings()
        )
    assert rows == [{"sku": "IGL-001", "supplier_name": "更新供应商"}]


def test_orders_enrichment_marks_linked_missing_and_blank_sku(
    sources_client: TestClient,
) -> None:
    _put_source(sources_client, "LINKED-001")
    order_id = _new_order(
        [
            {"name": "Linked item", "qty": 1, "sku": " linked-001 "},
            {"name": "Missing item", "qty": 2, "sku": "MISSING-001"},
            {"name": "Legacy item", "qty": 1},
        ]
    )

    response = sources_client.get("/api/app/w/orders", params={"filter": "all"})
    linked, missing, legacy = _response_items_for_order(response, order_id)

    assert linked["source_state"] == "linked"
    assert linked["source_url"] == _SOURCE_URL
    assert linked["supplier_name"] == "测试供应商"
    assert linked["currency"] == "CNY"
    assert linked["moq"] == 5
    assert missing["source_state"] == "missing"
    assert missing["source_url"] is None
    assert legacy["source_state"] == "missing"
    assert legacy["source_url"] is None


def test_orders_enrichment_uses_one_in_query_without_n_plus_one(
    sources_client: TestClient,
) -> None:
    for index in range(4):
        sku = f"BATCH-{index:03d}"
        _put_source(sources_client, sku)
        _new_order(
            [
                {"name": f"Batch {index}", "qty": 1, "sku": sku},
                {
                    "name": f"Missing {index}",
                    "qty": 1,
                    "sku": f"NO-SOURCE-{index:03d}",
                },
            ]
        )

    source_selects: list[str] = []

    def record_source_select(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if (
            "FROM w_product_sources" in statement
            and statement.lstrip().upper().startswith("SELECT")
        ):
            source_selects.append(statement)

    event.listen(db_engine, "before_cursor_execute", record_source_select)
    try:
        response = sources_client.get(
            "/api/app/w/orders",
            params={"filter": "all"},
        )
    finally:
        event.remove(db_engine, "before_cursor_execute", record_source_select)

    assert response.status_code == 200, response.text
    assert len(source_selects) == 1
    assert " IN (" in source_selects[0].upper()


def test_orders_source_query_failure_degrades_every_item_to_missing(
    sources_client: TestClient,
) -> None:
    _put_source(sources_client, "FAIL-SAFE-001")
    order_id = _new_order(
        [
            {"name": "Would be linked", "qty": 1, "sku": "FAIL-SAFE-001"},
            {"name": "Already missing", "qty": 1, "sku": "NO-SOURCE"},
        ]
    )

    def fail_source_select(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if (
            "FROM w_product_sources" in statement
            and statement.lstrip().upper().startswith("SELECT")
        ):
            raise SQLAlchemyError("forced product-source query failure")

    event.listen(db_engine, "before_cursor_execute", fail_source_select)
    try:
        response = sources_client.get(
            "/api/app/w/orders",
            params={"filter": "all"},
        )
    finally:
        event.remove(db_engine, "before_cursor_execute", fail_source_select)

    items = _response_items_for_order(response, order_id)
    assert [item["source_state"] for item in items] == ["missing", "missing"]
    assert all(item["source_url"] is None for item in items)


def test_read_permission_can_list_but_cannot_write_or_delete(
    sources_client: TestClient,
) -> None:
    username = f"w_source_reader_{uuid4().hex[:12]}"
    password = "w-source-example-reader-password"
    with SessionLocal() as db:
        upsert_permission_registry(db)
        reader = User(
            username=username,
            password_hash=hash_password(password),
            role="viewer",
            is_active=True,
            # 已完成入职的测试账号。模型里 must_change_password 默认为 True，
            # 而「强制改密码门」会把这类用户挡在所有业务接口之外（403）——
            # 不显式声明的话，测的就不是本条断言想测的东西。
            must_change_password=False,
        )
        db.add(reader)
        db.flush()
        reader_id = reader.id
        # 组织成员关系。少了这一行，C18H 中间件解析不出组织上下文，
        # 整个 /api/app/* 直接 403 —— 权限本身根本轮不到被检查。
        # （真实系统里账号是从用户管理建的，那条路会一并写成员关系；
        #  测试里直接 ORM 造用户就必须自己补。）
        db.add(
            OrgMembershipRecord(
                membership_id=str(uuid4()),
                user_id=str(reader_id),
                org_id=DEFAULT_TEST_ORG_DB_ID,
                role="member",
                status="active",
            )
        )
        db.commit()
        grant_permission(
            db,
            user_id=reader_id,
            permission_key="w.site_ops.read",
            reason="W source read-only permission test.",
        )

    response = sources_client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text

    response = sources_client.get("/api/app/w/sources")
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []

    response = sources_client.put(
        "/api/app/w/sources/READ-ONLY-001",
        json=_source_payload(),
    )
    assert response.status_code == 403, response.text

    response = sources_client.delete("/api/app/w/sources/READ-ONLY-001")
    assert response.status_code == 403, response.text
