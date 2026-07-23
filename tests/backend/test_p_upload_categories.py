from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.modules.p_series.contract.upload_package import (
    UPLOAD_PACKAGE_SCHEMA_VERSION,
)
from backend.app.modules.p_series.upload import assemble


pytestmark = pytest.mark.unit


class _RollbackDB:
    def __init__(self) -> None:
        self.rollback_calls = 0

    def rollback(self) -> None:
        self.rollback_calls += 1


class _FailingRollbackDB(_RollbackDB):
    def rollback(self) -> None:
        super().rollback()
        raise RuntimeError("mock rollback failure")


def _product(*, google_id: str | None = "222") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        product_key="p-category-contract",
        sku="P-CATEGORY-CONTRACT",
        product_name_en="Category contract product",
        product_type="simple_product",
        marketing_copy_json={
            "product_page_copy": {},
            "seo": {"url_slug": "short-category-product"},
        },
        regular_price=Decimal("19.99"),
        sale_price=None,
        price_currency="USD",
        stock_status="in_stock",
        inventory_quantity=3,
        google_product_category=google_id,
        merchant_product_type="Home & Garden > Kitchen",
        primary_keyword=None,
        shipping_class=None,
    )


@pytest.fixture(autouse=True)
def _isolate_package_assembly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assemble, "_image_assets", lambda *args, **kwargs: [])
    monkeypatch.setattr(assemble, "_variants", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        assemble,
        "build_description_html",
        lambda *args, **kwargs: {"html": "<p>Ready</p>", "sections_emitted": []},
    )


def _assemble(product: SimpleNamespace, db: object | None = None):
    return assemble.assemble_upload_package(
        db or object(),
        product,
        base_url="https://console.example.test",
    )


def test_assemble_includes_resolved_path_and_wc_leaf_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = object()
    resolved_path = [
        {"google_id": "100", "name": "Home & Garden"},
        {"google_id": "200", "name": "Kitchen & Dining"},
        {"google_id": "222", "name": "Kitchen Tools"},
    ]
    events: list[str] = []

    def variants(
        actual_db: object, product: SimpleNamespace, **kwargs: object
    ) -> list[object]:
        del product, kwargs
        assert actual_db is db
        events.append("variants")
        return []

    def resolve(actual_db: object, google_id: str) -> list[dict[str, str]]:
        assert actual_db is db
        assert google_id == "222"
        events.append("resolve")
        return resolved_path

    def ensure(actual_db: object, path: list[dict[str, str]]) -> int:
        assert actual_db is db
        assert path is resolved_path
        events.append("ensure")
        return 321

    monkeypatch.setattr(assemble, "_variants", variants)
    monkeypatch.setattr(assemble, "google_category_path", resolve)
    monkeypatch.setattr(assemble, "ensure_wc_category_path", ensure)

    payload = _assemble(_product(), db).model_dump(mode="json")

    assert payload["schema_version"] == "p-upload-package-v5"
    assert UPLOAD_PACKAGE_SCHEMA_VERSION == "p-upload-package-v5"
    assert payload["product"]["category"]["path"] == [
        "Home & Garden",
        "Kitchen & Dining",
        "Kitchen Tools",
    ]
    assert payload["product"]["category"]["wc_category_id"] == 321
    assert payload["product"]["seo"]["url_slug"] == "short-category-product"
    assert payload["product"]["category"]["slug"] == "short-category-product"
    # Category fail-safe may roll back; SKU finalization/variant reads therefore
    # happen only after the category transaction is settled.
    assert events == ["resolve", "ensure", "variants"]


def test_assemble_skips_wc_when_google_category_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        assemble,
        "google_category_path",
        lambda *args, **kwargs: calls.append("resolve"),
    )
    monkeypatch.setattr(
        assemble,
        "ensure_wc_category_path",
        lambda *args, **kwargs: calls.append("ensure"),
    )

    with caplog.at_level(logging.WARNING, logger=assemble.__name__):
        payload = _assemble(_product(google_id=None)).model_dump(mode="json")

    assert calls == []
    assert payload["product"]["category"]["path"] is None
    assert payload["product"]["category"]["wc_category_id"] is None
    assert "google_product_category missing" in caplog.text


def test_assemble_keeps_path_when_wc_ensure_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = _RollbackDB()
    resolved_path = [
        {"google_id": "100", "name": "Home & Garden"},
        {"google_id": "222", "name": "Kitchen Tools"},
    ]
    monkeypatch.setattr(
        assemble,
        "google_category_path",
        lambda *args, **kwargs: resolved_path,
    )

    def fail_ensure(*args: object, **kwargs: object) -> int:
        del args, kwargs
        raise RuntimeError("mock Woo failure")

    monkeypatch.setattr(assemble, "ensure_wc_category_path", fail_ensure)

    with caplog.at_level(logging.ERROR, logger=assemble.__name__):
        payload = _assemble(_product(), db).model_dump(mode="json")

    assert payload["product"]["category"]["path"] == [
        "Home & Garden",
        "Kitchen Tools",
    ]
    assert payload["product"]["category"]["wc_category_id"] is None
    assert db.rollback_calls == 1
    assert "Woo category ensure failed" in caplog.text
    assert "upload continues uncategorized" in caplog.text


def test_assemble_continues_when_google_path_resolution_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = _RollbackDB()

    def fail_resolution(*args: object, **kwargs: object) -> list[dict[str, str]]:
        del args, kwargs
        raise LookupError("mock path failure")

    monkeypatch.setattr(assemble, "google_category_path", fail_resolution)
    monkeypatch.setattr(
        assemble,
        "ensure_wc_category_path",
        lambda *args, **kwargs: pytest.fail("WC must not run without a path"),
    )

    with caplog.at_level(logging.ERROR, logger=assemble.__name__):
        payload = _assemble(_product(), db).model_dump(mode="json")

    assert payload["product"]["category"]["path"] is None
    assert payload["product"]["category"]["wc_category_id"] is None
    assert db.rollback_calls == 1
    assert "Google category path resolution failed" in caplog.text


def test_category_rollback_failure_does_not_escape_package_assembly(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = _FailingRollbackDB()

    def fail_resolution(*args: object, **kwargs: object) -> list[dict[str, str]]:
        del args, kwargs
        raise LookupError("mock path failure")

    monkeypatch.setattr(assemble, "google_category_path", fail_resolution)
    monkeypatch.setattr(
        assemble,
        "ensure_wc_category_path",
        lambda *args, **kwargs: pytest.fail("WC must not run without a path"),
    )

    with caplog.at_level(logging.ERROR, logger=assemble.__name__):
        payload = _assemble(_product(), db).model_dump(mode="json")

    assert payload["product"]["category"]["wc_category_id"] is None
    assert db.rollback_calls == 1
    assert "Woo category transaction rollback failed" in caplog.text


def test_n8n_only_sends_a_valid_wc_category_id() -> None:
    workflow_path = (
        Path(__file__).resolve().parents[2]
        / "backend/app/modules/p_series/n8n/p_upload_workflow.json"
    )
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    transform = next(
        node for node in workflow["nodes"] if node["name"] == "转 Woo 格式"
    )
    js_code = transform["parameters"]["jsCode"]

    assert "const category = p.category || {};" in js_code
    assert "const wcCategoryId = Number(category.wc_category_id);" in js_code
    assert "Number.isInteger(wcCategoryId) && wcCategoryId > 0" in js_code
    assert "body.categories = [{ id: wcCategoryId }];" in js_code
    assert js_code.count("body.categories") == 1
    assert "categories:" not in js_code
