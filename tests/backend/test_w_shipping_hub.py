"""W-S 物流网络中枢集成测试：规则查表、人工台账、P 硬门与上架契约。"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from backend.app.db.session import SessionLocal
from backend.app.modules.k_series.product_knowledge.models import (
    KProductKnowledgeProduct,
)
from backend.app.modules.p_series.upload.models import PUploadJob
from backend.app.modules.w_series.shipping import engine
from backend.app.modules.w_series.shipping.models import (
    WShippingClass,
    WShippingRule,
)

pytestmark = pytest.mark.integration

_SOURCE = "w_shipping_test"
_CLASSES = (
    ("w-test-us", "美国仓线", "us_stock", 10),
    ("w-test-battery", "带电线", "cn_direct", 20),
    ("w-test-small", "小件线", "cn_direct", 30),
    ("w-test-medium", "中件线", "cn_direct", 40),
    ("w-test-heavy", "重货线", "cn_direct", 50),
)


def _clean_w_rows() -> None:
    with SessionLocal() as db:
        db.execute(delete(PUploadJob).where(PUploadJob.job_id.like("w-test-%")))
        db.execute(
            delete(KProductKnowledgeProduct).where(
                KProductKnowledgeProduct.source_system == _SOURCE
            )
        )
        db.execute(delete(WShippingRule))
        db.execute(delete(WShippingClass))
        db.commit()


@pytest.fixture
def w_env(owner_client: TestClient) -> dict[str, object]:
    """种五个模板与覆盖/重量规则；每个用例前后彻底清理 W 测试数据。"""

    _clean_w_rows()
    with SessionLocal() as db:
        classes: dict[str, WShippingClass] = {}
        for slug, name, origin, sort_order in _CLASSES:
            row = WShippingClass(
                slug=slug,
                name=name,
                origin=origin,
                active=True,
                sort_order=sort_order,
            )
            db.add(row)
            classes[slug] = row
        db.flush()
        rules = [
            WShippingRule(
                priority=10,
                rule_type="us_stock_override",
                shipping_class_slug="w-test-us",
                active=True,
            ),
            WShippingRule(
                priority=20,
                rule_type="battery_override",
                shipping_class_slug="w-test-battery",
                active=True,
            ),
            WShippingRule(
                priority=100,
                rule_type="weight_band",
                min_weight_kg=Decimal("0"),
                max_weight_kg=Decimal("0.5"),
                shipping_class_slug="w-test-small",
                active=True,
            ),
            WShippingRule(
                priority=110,
                rule_type="weight_band",
                min_weight_kg=Decimal("0.5"),
                max_weight_kg=Decimal("2"),
                shipping_class_slug="w-test-medium",
                active=True,
            ),
            WShippingRule(
                priority=120,
                rule_type="weight_band",
                min_weight_kg=Decimal("2"),
                max_weight_kg=None,
                shipping_class_slug="w-test-heavy",
                active=True,
            ),
        ]
        db.add_all(rules)
        db.commit()
        class_ids = {slug: str(row.id) for slug, row in classes.items()}
        rule_ids = {row.rule_type + str(row.priority): str(row.id) for row in rules}

    yield {
        "client": owner_client,
        "class_ids": class_ids,
        "rule_ids": rule_ids,
    }
    _clean_w_rows()


def _new_product(
    *,
    weight_kg: float | None = None,
    shipping_class: str | None = None,
    assignment: dict[str, object] | None = None,
) -> UUID:
    with SessionLocal() as db:
        product = KProductKnowledgeProduct(
            product_key=f"w-test-product-{uuid4().hex}",
            source_system=_SOURCE,
            product_name_en="W shipping test product",
            sku=f"W-{uuid4().hex[:10]}",
            channel="dtc",
            package_weight_json=(
                {"value": weight_kg, "unit": "kg"}
                if weight_kg is not None
                else None
            ),
            shipping_class=shipping_class,
            contains_battery=False,
            us_stock=False,
            shipping_assignment_json=assignment,
            shipping_review_needed=False,
        )
        db.add(product)
        db.commit()
        return product.id


def test_shipping_class_and_rule_crud(w_env: dict[str, object]) -> None:
    client = w_env["client"]
    assert isinstance(client, TestClient)

    response = client.get("/api/app/w/shipping/classes")
    assert response.status_code == 200
    assert {item["slug"] for item in response.json()} >= {
        slug for slug, _name, _origin, _sort in _CLASSES
    }

    response = client.post(
        "/api/app/w/shipping/classes",
        json={
            "slug": "w-test-express",
            "name": "加急线",
            "origin": "cn_direct",
            "notes": "CRUD",
            "sort_order": 60,
        },
    )
    assert response.status_code == 201, response.text
    class_id = response.json()["id"]

    response = client.patch(
        f"/api/app/w/shipping/classes/{class_id}",
        json={"name": "加急线路", "active": False, "sort_order": 61},
    )
    assert response.status_code == 200
    assert response.json()["slug"] == "w-test-express"
    assert response.json()["active"] is False

    response = client.patch(
        f"/api/app/w/shipping/classes/{class_id}",
        json={"slug": "slug-cannot-change"},
    )
    assert response.status_code == 422

    response = client.post(
        "/api/app/w/shipping/rules",
        json={
            "priority": 500,
            "rule_type": "weight_band",
            "min_weight_kg": 20,
            "max_weight_kg": None,
            "shipping_class_slug": "w-test-express",
            "active": True,
            "notes": "CRUD",
        },
    )
    assert response.status_code == 201, response.text
    rule_id = response.json()["id"]

    response = client.patch(
        f"/api/app/w/shipping/rules/{rule_id}",
        json={"priority": 490, "active": False, "notes": "updated"},
    )
    assert response.status_code == 200
    assert response.json()["priority"] == 490
    assert response.json()["active"] is False

    response = client.get("/api/app/w/shipping/rules")
    assert response.status_code == 200
    priorities = [item["priority"] for item in response.json()]
    assert priorities == sorted(priorities)

    response = client.delete(f"/api/app/w/shipping/rules/{rule_id}")
    assert response.status_code == 204


@pytest.mark.parametrize(
    ("payload", "expected_slug", "expected_rule_type"),
    [
        (
            {
                "weight_kg": 0.05,
                "volumetric_kg": None,
                "contains_battery": False,
                "us_stock": False,
            },
            "w-test-small",
            "weight_band",
        ),
        (
            {
                "weight_kg": 5,
                "volumetric_kg": None,
                "contains_battery": False,
                "us_stock": False,
            },
            "w-test-heavy",
            "weight_band",
        ),
        (
            {
                "weight_kg": 2,
                "volumetric_kg": None,
                "contains_battery": True,
                "us_stock": False,
            },
            "w-test-battery",
            "battery_override",
        ),
        (
            {
                "weight_kg": 2,
                "volumetric_kg": None,
                "contains_battery": True,
                "us_stock": True,
            },
            "w-test-us",
            "us_stock_override",
        ),
    ],
)
def test_simulate_deterministic_rule_order(
    w_env: dict[str, object],
    payload: dict[str, object],
    expected_slug: str,
    expected_rule_type: str,
) -> None:
    client = w_env["client"]
    assert isinstance(client, TestClient)
    response = client.post("/api/app/w/shipping/simulate", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["shipping_class_slug"] == expected_slug
    assert result["rule_type"] == expected_rule_type


def test_volume_weight_missing_weight_and_boundary_review(
    w_env: dict[str, object],
) -> None:
    with SessionLocal() as db:
        rules = list(
            db.scalars(
                select(WShippingRule).order_by(WShippingRule.priority.asc())
            ).all()
        )
        bulky_product = SimpleNamespace(
            package_weight_json={"value": 1, "unit": "kg"},
            weight_json=None,
            package_dimensions_json={
                "length": 30,
                "width": 40,
                "height": 50,
                "unit": "cm",
            },
            contains_battery=False,
            us_stock=False,
        )
        decision = engine.evaluate_product(rules, bulky_product)
    assert decision.volumetric_kg == 10
    assert decision.used_kg == 10
    assert decision.shipping_class_slug == "w-test-heavy"

    client = w_env["client"]
    assert isinstance(client, TestClient)
    response = client.post(
        "/api/app/w/shipping/simulate",
        json={
            "weight_kg": None,
            "volumetric_kg": None,
            "contains_battery": False,
            "us_stock": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["shipping_class_slug"] is None
    assert response.json()["review_needed"] is True
    assert response.json()["review_reason"] == "重量数据缺失，无法确定性分配"

    response = client.post(
        "/api/app/w/shipping/simulate",
        json={
            "weight_kg": 1.95,
            "volumetric_kg": None,
            "contains_battery": False,
            "us_stock": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["shipping_class_slug"] == "w-test-medium"
    assert response.json()["review_needed"] is True
    assert response.json()["review_reason"] == (
        "计费重 1.95kg 接近段位边界，请人工复核"
    )


def test_manual_assignment_is_protected_unless_forced(
    w_env: dict[str, object],
) -> None:
    client = w_env["client"]
    assert isinstance(client, TestClient)
    product_id = _new_product(weight_kg=5)

    response = client.patch(
        f"/api/app/w/shipping/products/{product_id}",
        json={"shipping_class_slug": "w-test-small"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["assignment"]["rule_type"] == "manual"

    response = client.post(
        f"/api/app/w/shipping/assign/{product_id}",
        json={"force": False},
    )
    assert response.status_code == 200
    assert response.json()["skipped_manual"] is True
    assert response.json()["shipping_class_slug"] == "w-test-small"

    response = client.patch(
        f"/api/app/w/shipping/products/{product_id}",
        json={"shipping_class_slug": None},
    )
    assert response.status_code == 200
    assert response.json()["shipping_class_slug"] is None
    assert response.json()["assignment"] is None

    response = client.post(
        f"/api/app/w/shipping/assign/{product_id}",
        json={"force": False},
    )
    assert response.status_code == 200
    assert response.json()["skipped_manual"] is False
    assert response.json()["shipping_class_slug"] == "w-test-heavy"

    response = client.patch(
        f"/api/app/w/shipping/products/{product_id}",
        json={"shipping_class_slug": "w-test-small"},
    )
    assert response.status_code == 200

    response = client.post(
        f"/api/app/w/shipping/assign/{product_id}",
        json={"force": True},
    )
    assert response.status_code == 200
    assert response.json()["skipped_manual"] is False
    assert response.json()["shipping_class_slug"] == "w-test-heavy"
    assert response.json()["rule_type"] == "weight_band"


def test_p_shipping_gate_only_blocks_dtc(
    w_env: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    del w_env
    from backend.app.modules.p_series.upload import assemble

    monkeypatch.setattr(assemble, "_has_bound_image", lambda db, product: True)
    monkeypatch.setattr(assemble, "category_is_bound", lambda product: True)
    monkeypatch.setattr(assemble, "audit_gate_blockers", lambda db, product: [])
    product = SimpleNamespace(
        id=uuid4(),
        product_name_en="Ready product",
        marketing_copy_json={"product_page_copy": {}},
        regular_price=Decimal("9.99"),
        channel="dtc",
        shipping_class=None,
    )
    with SessionLocal() as db:
        blockers = assemble.gate_blockers(db, product)
        assert "运费模板未分配（去 W-S 物流网络中枢处理）" in blockers

        product.shipping_class = "w-test-small"
        blockers = assemble.gate_blockers(db, product)
        assert "运费模板未分配（去 W-S 物流网络中枢处理）" not in blockers

        product.shipping_class = None
        product.channel = "amazon"
        blockers = assemble.gate_blockers(db, product)
        assert "运费模板未分配（去 W-S 物流网络中枢处理）" not in blockers


def test_upload_package_contains_shipping_class(
    w_env: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    del w_env
    from backend.app.modules.p_series.upload import assemble

    monkeypatch.setattr(assemble, "_image_assets", lambda *args, **kwargs: [])
    monkeypatch.setattr(assemble, "_variants", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        assemble,
        "build_description_html",
        lambda *args, **kwargs: {"html": "<p>Ready</p>", "sections_emitted": []},
    )
    product = SimpleNamespace(
        id=uuid4(),
        product_key="w-contract-product",
        sku="W-CONTRACT",
        product_name_en="Contract product",
        product_type="simple_product",
        marketing_copy_json={"product_page_copy": {}},
        regular_price=Decimal("9.99"),
        sale_price=None,
        price_currency="USD",
        stock_status="in_stock",
        inventory_quantity=5,
        google_product_category="123",
        merchant_product_type="Example",
        primary_keyword=None,
        shipping_class="w-test-small",
    )
    with SessionLocal() as db:
        package = assemble.assemble_upload_package(
            db,
            product,
            base_url="https://example.test",
        )
    payload = package.model_dump(mode="json")
    assert payload["shipping"]["shipping_class"] == "w-test-small"


def test_board_exported_missing_filter(w_env: dict[str, object]) -> None:
    client = w_env["client"]
    assert isinstance(client, TestClient)
    product_id = _new_product(weight_kg=1, shipping_class=None)
    with SessionLocal() as db:
        db.add(
            PUploadJob(
                job_id=f"w-test-{uuid4().hex}",
                product_id=product_id,
                channel="woocommerce",
                status="success",
                token=uuid4().hex,
            )
        )
        db.commit()

    response = client.get(
        "/api/app/w/shipping/board",
        params={"filter": "exported_missing", "limit": 500},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["summary"]["exported_missing"] == 1
    assert [item["product_id"] for item in result["items"]] == [str(product_id)]
    assert result["items"][0]["exported"] is True
    assert result["items"][0]["shipping_class_slug"] is None


def test_w_endpoints_require_permission(
    w_env: dict[str, object], auth_client: TestClient
) -> None:
    from backend.app.core.security import hash_password
    from backend.app.models.user import User

    username = "w_series_plain_viewer"
    password = "w-series-example-viewer-pass"
    with SessionLocal() as db:
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                role="viewer",
                is_active=True,
            )
        )
        db.commit()

    response = auth_client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200

    class_ids = w_env["class_ids"]
    rule_ids = w_env["rule_ids"]
    assert isinstance(class_ids, dict)
    assert isinstance(rule_ids, dict)
    class_id = class_ids["w-test-small"]
    rule_id = rule_ids["weight_band100"]
    missing_product_id = str(uuid4())
    requests = (
        ("GET", "/api/app/w/shipping/classes", None),
        (
            "POST",
            "/api/app/w/shipping/classes",
            {"slug": "denied", "name": "Denied", "origin": "cn_direct"},
        ),
        (
            "PATCH",
            f"/api/app/w/shipping/classes/{class_id}",
            {"name": "Denied"},
        ),
        ("GET", "/api/app/w/shipping/rules", None),
        (
            "POST",
            "/api/app/w/shipping/rules",
            {
                "priority": 999,
                "rule_type": "weight_band",
                "shipping_class_slug": "w-test-small",
            },
        ),
        (
            "PATCH",
            f"/api/app/w/shipping/rules/{rule_id}",
            {"priority": 999},
        ),
        ("DELETE", f"/api/app/w/shipping/rules/{rule_id}", None),
        (
            "POST",
            "/api/app/w/shipping/simulate",
            {
                "weight_kg": 1,
                "volumetric_kg": None,
                "contains_battery": False,
                "us_stock": False,
            },
        ),
        (
            "POST",
            f"/api/app/w/shipping/assign/{missing_product_id}",
            {"force": False},
        ),
        ("POST", "/api/app/w/shipping/assign-all", None),
        ("GET", "/api/app/w/shipping/board", None),
        (
            "PATCH",
            f"/api/app/w/shipping/products/{missing_product_id}",
            {"contains_battery": True},
        ),
    )
    for method, path, payload in requests:
        response = auth_client.request(method, path, json=payload)
        assert response.status_code == 403, f"{method} {path}: {response.text}"
