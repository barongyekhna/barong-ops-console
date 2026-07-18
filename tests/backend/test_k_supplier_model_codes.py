from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Request

from backend.app.modules.k_series.product_knowledge import router as k_router
from backend.app.modules.k_series.product_knowledge.product_naming import (
    sanitize_product_naming_output,
    strip_supplier_model_codes,
)


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "DS-101 Portable Cookware 7-Piece 1.5L Set",
            "Portable Cookware 7-Piece 1.5L Set",
        ),
        ("DS308 Portable Cookware", "Portable Cookware"),
        (
            "Portable Cookware (DS-101) - 2-3 Person Set",
            "Portable Cookware - 2-3 Person Set",
        ),
        ("Portable Cookware, DS-101, 7-Piece Set", "Portable Cookware, 7-Piece Set"),
        ("7-Piece 1.5L Set for 2-3 People", "7-Piece 1.5L Set for 2-3 People"),
        ("\u708a\u5177DS-101\u4fbf\u643a", "\u708a\u5177\u4fbf\u643a"),
        (
            "IP68 IP65 UPF50 UV400 AC110/DC12 Outdoor Cover",
            "IP68 IP65 UPF50 UV400 AC110/DC12 Outdoor Cover",
        ),
        ("ds-101 Portable Cookware", "ds-101 Portable Cookware"),
        ("DS101A Portable Cookware", "DS101A Portable Cookware"),
        ("DS-101", ""),
    ],
)
def test_strip_supplier_model_codes_preserves_numeric_specs(
    source: str,
    expected: str,
) -> None:
    assert strip_supplier_model_codes(source) == expected


def test_sanitize_product_naming_output_copies_and_limits_scope() -> None:
    source = {
        "product_name_en": "DS308 Outdoor Cover IP68 UPF50 UV400 AC110/DC12",
        "structured_specs": {"model": "DS308", "rating": "IP68"},
    }

    sanitized = sanitize_product_naming_output(source)

    assert sanitized == {
        "product_name_en": "Outdoor Cover IP68 UPF50 UV400 AC110/DC12",
        "structured_specs": {"model": "DS308", "rating": "IP68"},
    }
    assert source["product_name_en"].startswith("DS308")


def test_standalone_deepseek_route_sanitizes_stored_and_returned_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = SimpleNamespace(
        id=uuid4(),
        product_key="route-model-cleanup",
        raw_input_text="Supplier title DS-101",
        deepseek_structured_output_json=None,
        review_status="draft",
    )
    provider_output = {
        "product_name_en": "DS-101 Outdoor Cover IP68 UPF50 UV400 AC110/DC12",
        "structured_specs": {"supplier_model": "DS-101"},
    }
    context = SimpleNamespace(
        key_for_step=lambda _step: SimpleNamespace(name="deepseek")
    )

    class FakeRead:
        def model_dump(self, **_kwargs):
            return {"product_key": product.product_key}

    class FakeDB:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.flushed = False

        def add_all(self, values) -> None:
            self.added.extend(values)

        def flush(self) -> None:
            self.flushed = True

    db = FakeDB()
    request = Request({"type": "http", "method": "POST", "path": "/"})
    request.state.org_id = "org_model_cleanup"
    monkeypatch.setattr(k_router, "_execution_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(k_router, "_product_by_ref", lambda *args, **kwargs: product)
    monkeypatch.setattr(
        k_router,
        "_execute_provider_json",
        lambda *args, **kwargs: provider_output,
    )
    monkeypatch.setattr(
        k_router.ProductKnowledgeRead,
        "model_validate",
        lambda _product: FakeRead(),
    )

    response = k_router.deepseek_enrich_product(
        product_id=product.product_key,
        request=request,
        db=db,  # type: ignore[arg-type]
        user=SimpleNamespace(),  # type: ignore[arg-type]
    )

    expected_name = "Outdoor Cover IP68 UPF50 UV400 AC110/DC12"
    assert response.output["product_name_en"] == expected_name
    assert product.deepseek_structured_output_json["product_name_en"] == expected_name
    assert product.deepseek_structured_output_json["structured_specs"] == {
        "supplier_model": "DS-101"
    }
    assert db.flushed is True
    event = db.added[1]
    assert event.output_payload_json["product_name_en"] == expected_name
