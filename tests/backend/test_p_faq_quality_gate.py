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

from backend.app.modules.p_series import router as p_router
from backend.app.modules.p_series.upload import assemble
from backend.app.modules.p_series.upload.description_html import (
    build_description_html,
    build_schema_jsonld,
)
from backend.app.modules.p_series.upload.faq_publication_audit import (
    audit_published_faq,
    audit_published_faq_html,
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


def test_published_faq_audit_accepts_schema_from_the_visible_faq_block() -> None:
    html = """
    <section class="kp-faq">
      <details><summary>Will fuel pressure change in cold weather?</summary>
      <div><p>Follow the fuel maker's approved temperature guidance.</p></div>
      </details>
    </section>
    <script type="application/ld+json">
      {"@context":"https://schema.org","@graph":[{"@type":"FAQPage",
       "mainEntity":[{"@type":"Question",
       "name":"Will fuel pressure change in cold weather?",
       "acceptedAnswer":{"@type":"Answer",
       "text":"Follow the fuel maker's approved temperature guidance."}}]}]}
    </script>
    """

    audit = audit_published_faq_html(
        html,
        page_url="https://shop.example.test/product/pump",
    )

    assert audit["status"] == "passed"
    assert audit["schema_faq_count"] == 1
    assert audit["visible_faq_present"] is True
    assert audit["missing_from_visible"] == []


def test_published_faq_audit_reports_stale_schema_question() -> None:
    html = """
    <section class="kp-faq">
      <details><summary>How should titanium cookware be cleaned?</summary>
      <div><p>Use the care method provided with the product.</p></div></details>
    </section>
    <script type="application/ld+json">
      {"@type":"FAQPage","mainEntity":[{"@type":"Question",
       "name":"Does the kettle work in cold weather?",
       "acceptedAnswer":{"@type":"Answer","text":"Keep the kettle warm."}}]}
    </script>
    """

    audit = audit_published_faq_html(html)

    assert audit["status"] == "mismatch"
    assert audit["ok"] is False
    assert audit["missing_from_visible"] == [
        {
            "question": "Does the kettle work in cold weather?",
            "missing_fields": ["question", "answer"],
        }
    ]


def test_upload_callback_faq_mismatch_alert_is_error_and_fail_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mismatch = {
        "status": "mismatch",
        "ok": False,
        "schema_faq_count": 1,
        "missing_from_visible": [{"question": "Stale FAQ"}],
    }
    notifications: list[dict[str, Any]] = []
    monkeypatch.setattr(
        p_router,
        "audit_published_faq",
        lambda _url, **_kwargs: mismatch,
    )
    monkeypatch.setattr(
        p_router,
        "get_settings",
        lambda: SimpleNamespace(wp_base_url="https://shop.example.test"),
    )
    monkeypatch.setattr(
        p_router,
        "create_notification",
        lambda _db, **kwargs: notifications.append(kwargs),
    )

    result = p_router._audit_published_faq_after_success(
        object(),  # type: ignore[arg-type]
        product_id=uuid4(),
        external_product_id="3822",
        external_url="https://shop.example.test/product/new-product",
    )

    assert result == mismatch
    assert notifications[0]["event_type"] == "p.upload.faq_sync_mismatch"
    assert notifications[0]["level"] == "error"
    assert notifications[0]["payload"] == mismatch


def test_published_faq_fetch_rejects_an_off_origin_page_before_opening() -> None:
    opened = False

    def opener(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal opened
        opened = True
        raise AssertionError("off-origin URL must be rejected before fetch")

    with pytest.raises(ValueError, match="configured WordPress origin"):
        audit_published_faq(
            "http://127.0.0.1/internal",
            allowed_base_url="https://shop.example.test",
            opener=opener,
        )
    assert opened is False


def test_published_faq_fetch_rejects_an_off_origin_final_redirect() -> None:
    class RedirectedResponse:
        headers = None

        def __enter__(self) -> "RedirectedResponse":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def geturl(self) -> str:
            return "https://attacker.example.test/redirected"

        def read(self, _limit: int) -> bytes:
            raise AssertionError("redirect target body must not be read")

    with pytest.raises(ValueError, match="configured WordPress origin"):
        audit_published_faq(
            "https://shop.example.test/product/new-product",
            allowed_base_url="https://shop.example.test",
            opener=lambda *_args, **_kwargs: RedirectedResponse(),
        )


def test_upload_callback_missing_wp_base_alerts_without_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[dict[str, Any]] = []
    monkeypatch.setattr(
        p_router,
        "get_settings",
        lambda: SimpleNamespace(wp_base_url=None),
    )
    monkeypatch.setattr(
        p_router,
        "create_notification",
        lambda _db, **kwargs: notifications.append(kwargs),
    )

    result = p_router._audit_published_faq_after_success(
        object(),  # type: ignore[arg-type]
        product_id=uuid4(),
        external_product_id="3822",
        external_url="https://shop.example.test/product/new-product",
    )

    assert result["status"] == "audit_failed"
    assert result["error_class"] == "ValueError"
    assert notifications[0]["event_type"] == "p.upload.faq_audit_failed"
    assert notifications[0]["level"] == "error"


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


def test_n8n_overwrites_faq_meta_for_eligible_empty_and_ineligible_packages() -> None:
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
                "html": (
                    '<section class="kp-faq"><details><summary>'
                    "Will fuel pressure change in cold weather?"
                    "</summary><p>Use the fuel maker's approved temperature range."
                    "</p></details></section>"
                ),
                "faq": faq,
            },
            "category": {},
            "seo": {},
        },
        "shipping": {},
    }

    legacy_body = _run_n8n_transform(package)
    assert legacy_body["description"] == package["product"]["description"]["html"]
    assert legacy_body["meta_data"] == [{"key": "_kp_faq", "value": ""}]

    package["product"]["description"]["faq_schema_eligible"] = False
    low_quality_body = _run_n8n_transform(package)
    assert low_quality_body["meta_data"] == [{"key": "_kp_faq", "value": ""}]

    package["product"]["description"]["faq_schema_eligible"] = True
    eligible_body = _run_n8n_transform(package)
    assert eligible_body["meta_data"] == [
        {"key": "_kp_faq", "value": json.dumps(faq, separators=(",", ":"))}
    ]
