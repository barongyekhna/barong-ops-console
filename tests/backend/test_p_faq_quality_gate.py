from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from backend.app.modules.p_series.upload import assemble
from backend.app.modules.p_series.upload.description_html import (
    build_description_html,
    build_schema_jsonld,
)


pytestmark = pytest.mark.unit


def _marketing_copy(*, eligible: bool | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "product_page_copy": {},
        "page_faq": [
            {
                "question": "Will fuel pressure change in cold weather?",
                "answer": "Use the fuel maker's approved temperature range.",
                "evidence_refs": ["faq-src-cold-weather"],
            }
        ],
    }
    if eligible is not None:
        result["faq_quality"] = {"eligible_for_schema": eligible}
    return result


def test_visible_faq_survives_when_too_few_questions_qualify_for_schema() -> None:
    marketing_copy = _marketing_copy(eligible=False)

    description = build_description_html(marketing_copy)

    assert "Will fuel pressure change in cold weather?" in description["html"]
    assert "kp-faq" in description["sections_emitted"]
    assert "FAQPage" not in build_schema_jsonld(marketing_copy)


def test_faq_jsonld_requires_explicit_true_quality_verdict() -> None:
    eligible = _marketing_copy(eligible=True)
    assert "FAQPage" in build_schema_jsonld(eligible)

    legacy = _marketing_copy(eligible=None)
    assert "Will fuel pressure change in cold weather?" in build_description_html(
        legacy
    )["html"]
    assert build_schema_jsonld(legacy) == ""

    malformed = _marketing_copy(eligible=None)
    malformed["faq_quality"] = "legacy"
    assert build_schema_jsonld(malformed) == ""

    malformed["page_faq"] = 7
    assert "kp-faq" not in build_description_html(malformed)["html"]
    assert build_schema_jsonld(malformed) == ""


def _product(marketing_copy_json: Any) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        product_key="faq-quality-contract",
        sku="FAQ-001",
        product_name_en="FAQ quality contract product",
        product_type="simple_product",
        marketing_copy_json=marketing_copy_json,
        regular_price=Decimal("19.99"),
        sale_price=None,
        price_currency="USD",
        stock_status="in_stock",
        inventory_quantity=3,
        google_product_category=None,
        merchant_product_type=None,
        primary_keyword=None,
        shipping_class=None,
    )


def test_upload_package_carries_strict_faq_schema_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(assemble, "_image_assets", lambda *args, **kwargs: [])
    monkeypatch.setattr(assemble, "_variants", lambda *args, **kwargs: [])

    legacy = assemble.assemble_upload_package(
        object(),
        _product(_marketing_copy(eligible=None)),
        base_url="https://console.example.test",
    )
    assert len(legacy.product.description.faq) == 1
    assert legacy.product.description.faq_schema_eligible is False

    qualified = assemble.assemble_upload_package(
        object(),
        _product(_marketing_copy(eligible=True)),
        base_url="https://console.example.test",
    )
    assert len(qualified.product.description.faq) == 1
    assert qualified.product.description.faq_schema_eligible is True

    malformed = assemble.assemble_upload_package(
        object(),
        _product(["legacy copy shape"]),
        base_url="https://console.example.test",
    )
    assert malformed.product.description.faq == []
    assert malformed.product.description.faq_schema_eligible is False


def _run_n8n_transform(package: dict[str, Any]) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to execute the n8n Code-node contract")
    workflow_path = (
        Path(__file__).resolve().parents[2]
        / "backend/app/modules/p_series/n8n/p_upload_workflow.json"
    )
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    code = next(
        item for item in workflow["nodes"] if item["name"] == "转 Woo 格式"
    )["parameters"]["jsCode"]
    runner = """
const code = JSON.parse(process.argv[1]);
const pkg = JSON.parse(process.argv[2]);
const $ = (name) => ({
  first: () => ({ json: pkg }),
  all: () => [],
});
const $input = { all: () => [] };
const result = new Function('$', '$input', code)($, $input);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "-e", runner, json.dumps(code), json.dumps(package)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)[0]["json"]["woo_body"]


def test_n8n_emits_faq_meta_only_for_explicitly_eligible_package() -> None:
    faq = [
        {
            "question": "Will fuel pressure change in cold weather?",
            "answer": "Use the fuel maker's approved temperature range.",
        }
    ]
    package = {
        "product": {
            "title": "Portable stove",
            "sku": "FAQ-001",
            "price": {"regular": "19.99"},
            "stock": {"status": "in_stock"},
            "description": {
                "html": "<section class=\"kp-faq\">Visible FAQ</section>",
                "faq": faq,
            },
            "category": {},
            "seo": {},
        },
        "shipping": {},
    }

    legacy_body = _run_n8n_transform(package)
    assert legacy_body["description"] == package["product"]["description"]["html"]
    assert all(item["key"] != "_kp_faq" for item in legacy_body["meta_data"])

    package["product"]["description"]["faq_schema_eligible"] = False
    low_quality_body = _run_n8n_transform(package)
    assert all(
        item["key"] != "_kp_faq" for item in low_quality_body["meta_data"]
    )

    package["product"]["description"]["faq_schema_eligible"] = True
    eligible_body = _run_n8n_transform(package)
    assert eligible_body["meta_data"] == [
        {"key": "_kp_faq", "value": json.dumps(faq, separators=(",", ":"))}
    ]
