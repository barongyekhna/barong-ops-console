from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

from backend.app.modules.p_series.upload.product_schema import (
    project_verified_product_specs,
)


pytestmark = pytest.mark.unit


def _run_n8n_code(
    code: str,
    *,
    nodes: dict[str, Any],
    input_json: dict[str, Any],
) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to execute the n8n Code-node contract")
    runner = """
const code = JSON.parse(process.argv[1]);
const nodes = JSON.parse(process.argv[2]);
const inputJson = JSON.parse(process.argv[3]);
const items = (value) => (Array.isArray(value) ? value : [value])
  .map((json) => ({ json }));
const $ = (name) => ({
  first: () => items(nodes[name])[0],
  all: () => items(nodes[name]),
});
const inputItems = items(inputJson);
const $input = {
  first: () => inputItems[0],
  all: () => inputItems,
};
const result = new Function('$', '$input', code)($, $input);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [
            node,
            "-e",
            runner,
            json.dumps(code),
            json.dumps(nodes),
            json.dumps(input_json),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _verified_specs() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "source": {"platform": "1688", "offer_id": "123"},
        "lumens": {
            "value": 300,
            "unit": "lm",
            "raw_value": "300流明",
            "source_label": "光通量",
        },
        "ip_rating": {
            "value": "IP65",
            "raw_value": "IP65",
            "source_label": "防护等级",
        },
        "runtime_h": {
            "value": {"min": 8, "max": 12},
            "unit": "h",
            "raw_value": "8-12小时",
            "source_label": "续航时间",
        },
        "dimensions": {
            "length": {"value": 18},
            "height": {"value": 42},
            "unit": "cm",
            "raw_value": "18x42cm",
            "source_label": "产品尺寸",
        },
        "additional_specs": [
            {
                "key": "solar_panel",
                "label": "Solar Panel",
                "value": "Monocrystalline",
                "raw_value": "单晶硅",
            }
        ],
    }


def test_verified_specs_feed_woo_attributes_and_schema_property_values() -> None:
    attributes, schema = project_verified_product_specs(_verified_specs())

    assert [item.model_dump() for item in attributes] == [
        {"name": "Luminous Flux", "value": "300", "unit": "lm"},
        {"name": "Runtime", "value": "8–12", "unit": "h"},
        {"name": "IP Rating", "value": "IP65", "unit": None},
        {"name": "Length", "value": "18", "unit": "cm"},
        {"name": "Height", "value": "42", "unit": "cm"},
        {"name": "Solar Panel", "value": "Monocrystalline", "unit": None},
    ]
    assert [item.model_dump() for item in schema.additional_property] == [
        {
            "type": "PropertyValue",
            "name": "Luminous Flux",
            "value": "300",
            "unit_text": "lm",
        },
        {
            "type": "PropertyValue",
            "name": "Runtime",
            "value": "8–12",
            "unit_text": "h",
        },
        {
            "type": "PropertyValue",
            "name": "IP Rating",
            "value": "IP65",
            "unit_text": None,
        },
        {
            "type": "PropertyValue",
            "name": "Length",
            "value": "18",
            "unit_text": "cm",
        },
        {
            "type": "PropertyValue",
            "name": "Height",
            "value": "42",
            "unit_text": "cm",
        },
        {
            "type": "PropertyValue",
            "name": "Solar Panel",
            "value": "Monocrystalline",
            "unit_text": None,
        },
    ]


def test_unverified_or_evidence_free_specs_never_become_product_claims() -> None:
    untrusted = _verified_specs()
    untrusted["source"] = {"platform": "ai"}
    attributes, schema = project_verified_product_specs(untrusted)
    assert attributes == []
    assert schema.additional_property == []

    evidence_free = _verified_specs()
    evidence_free["lumens"] = {"value": 9999, "unit": "lm"}
    attributes, schema = project_verified_product_specs(evidence_free)
    assert all(item.name != "Luminous Flux" for item in attributes)
    assert all(
        item.name != "Luminous Flux" for item in schema.additional_property
    )


def test_operator_facts_feed_attributes_and_schema_only_with_explicit_stamps() -> None:
    operator_specs = {
        "schema_version": "1.0",
        "source": {
            "platform": "operator",
            "evidence_type": "operator_fact",
        },
        "material": {
            "value": "Stainless steel",
            "evidence": "operator_fact",
        },
        "dimensions": {
            "length": {"value": 12},
            "unit": "cm",
            "evidence": "operator_fact",
        },
        "runtime_h": {"value": 8},
        "additional_specs": [
            {
                "key": "fuel_type",
                "label": "Fuel Type",
                "value": "Butane",
                "raw_value": "Butane",
                "evidence": "operator_fact",
            },
            {
                "key": "unstamped_claim",
                "label": "Unstamped Claim",
                "value": "Must stay private",
                "raw_value": "Must stay private",
            },
        ],
    }

    attributes, schema = project_verified_product_specs(operator_specs)

    assert [item.model_dump() for item in attributes] == [
        {"name": "Length", "value": "12", "unit": "cm"},
        {"name": "Material", "value": "Stainless steel", "unit": None},
        {"name": "Fuel Type", "value": "Butane", "unit": None},
    ]
    assert [item.name for item in schema.additional_property] == [
        "Length",
        "Material",
        "Fuel Type",
    ]
    assert all(item.name != "Runtime" for item in schema.additional_property)

    missing_root_stamp = {
        **operator_specs,
        "source": {"platform": "operator"},
    }
    attributes, schema = project_verified_product_specs(missing_root_stamp)
    assert attributes == []
    assert schema.additional_property == []


def test_wordpress_filter_preserves_woo_owned_real_review_fields() -> None:
    plugin = (
        Path(__file__).resolve().parents[2]
        / "backend/app/modules/p_series/wordpress/kp-product-structured-data.php"
    ).read_text(encoding="utf-8")

    assert "woocommerce_structured_data_product" in plugin
    assert "woocommerce_structured_data_product_offer" in plugin
    assert "wpseo_schema_product" in plugin
    assert "wpseo_schema_offer" in plugin
    assert "additionalProperty" in plugin
    assert "PropertyValue" in plugin
    assert "Barong Yekhna" in plugin
    assert "PHP_INT_MAX" in plugin
    assert "get_sale_price" in plugin
    assert "get_regular_price" in plugin
    assert "priceValidUntil" in plugin
    assert "priceCurrency" in plugin
    assert "availability" in plugin
    assert "itemCondition" in plugin
    assert "_yoast_wpseo_metadesc" in plugin
    assert "_yoast_wpseo_title" in plugin
    assert "html_entity_decode" in plugin
    assert "$product->get_description()" not in plugin
    # This adapter must never manufacture or override review data. Woo core
    # owns it and conditionally emits it from real approved reviews.
    assert "$markup['aggregateRating']" not in plugin
    assert "$markup['review']" not in plugin


def test_n8n_transform_sends_only_k_short_slug_to_woocommerce() -> None:
    workflow_path = (
        Path(__file__).resolve().parents[2]
        / "backend/app/modules/p_series/n8n/p_upload_workflow.json"
    )
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    code = next(
        item for item in workflow["nodes"] if item["name"] == "转 Woo 格式"
    )["parameters"]["jsCode"]
    package = {
        "product": {
            "title": "Long H1 That Must Never Become The Product URL",
            "sku": "CCD-002",
            "price": {"regular": "39.99", "sale": "34.99"},
            "stock": {"status": "in_stock"},
            "description": {"html": "<p>Clean copy.</p>", "faq": []},
            "category": {},
            "seo": {
                "title": "Camp Stove & Cookset",
                "description": "A clean authored description.",
                "url_slug": "compact-camp-stove",
            },
        },
        "shipping": {},
    }

    transformed = _run_n8n_code(
        code,
        nodes={"取数-上架包": package, "拆图": []},
        input_json=[],
    )[0]["json"]["woo_body"]

    assert transformed["name"] == package["product"]["title"]
    assert transformed["slug"] == "compact-camp-stove"
    assert transformed["regular_price"] == "39.99"
    assert transformed["sale_price"] == "34.99"
    assert transformed["meta_data"] == [
        {"key": "_yoast_wpseo_title", "value": "Camp Stove & Cookset"},
        {
            "key": "_yoast_wpseo_metadesc",
            "value": "A clean authored description.",
        },
    ]

    package["product"]["seo"].pop("url_slug")
    without_k_slug = _run_n8n_code(
        code,
        nodes={"取数-上架包": package, "拆图": []},
        input_json=[],
    )[0]["json"]["woo_body"]
    assert "slug" not in without_k_slug


def test_n8n_writes_specs_to_visible_attributes_and_schema_meta() -> None:
    workflow_path = (
        Path(__file__).resolve().parents[2]
        / "backend/app/modules/p_series/n8n/p_upload_workflow.json"
    )
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    node = next(
        item for item in workflow["nodes"] if item["name"] == "添加规格与Schema"
    )
    code = node["parameters"]["jsCode"]

    assert "body.attributes = attrs" in code
    assert "pkg.schema_version !== 'p-upload-package-v4'" in code
    assert "if (attrs.length)" not in code
    assert "visible: true" in code
    assert "variation: false" in code
    assert "'@type': 'PropertyValue'" in code
    assert "property.unitText" in code
    assert "key: '_kp_additional_property'" in code
    assert "value: JSON.stringify(properties)" in code
    assert "if (properties.length)" not in code
    assert "_kp_managed_attribute_names" in code
    assert (
        workflow["connections"]["转 Woo 格式"]["main"][0][0]["node"]
        == "添加规格与Schema"
    )
    publish_mode = next(
        item for item in workflow["nodes"] if item["name"] == "定上架方式"
    )
    publish_code = publish_mode["parameters"]["jsCode"]
    assert "$('添加规格与Schema')" in publish_code
    assert "oldOwnedNames" in publish_code
    assert "const preserved" in publish_code
    assert "pkg.woo_existing_product_id" in publish_code

    lookup = next(item for item in workflow["nodes"] if item["name"] == "查已有SKU")
    lookup_url = lookup["parameters"]["url"]
    assert "woo_existing_product_id" in lookup_url
    assert "woo_lookup_sku" in lookup_url


def test_n8n_preserves_manual_attributes_and_removes_only_pipeline_owned_specs() -> None:
    workflow_path = (
        Path(__file__).resolve().parents[2]
        / "backend/app/modules/p_series/n8n/p_upload_workflow.json"
    )
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    add_code = next(
        item for item in workflow["nodes"] if item["name"] == "添加规格与Schema"
    )["parameters"]["jsCode"]
    publish_code = next(
        item for item in workflow["nodes"] if item["name"] == "定上架方式"
    )["parameters"]["jsCode"]

    package = {
        "schema_version": "p-upload-package-v4",
        "woo_lookup_sku": "B0BYTEST01",
        "woo_existing_product_id": "3778",
        "product": {
            "attributes": [
                {"name": "Luminous Flux", "value": "300", "unit": "lm"}
            ],
            "structured_data": {"additional_property": []},
        },
    }
    added = _run_n8n_code(
        add_code,
        nodes={"取数-上架包": package},
        input_json={"woo_body": {"sku": "IGL-001", "meta_data": []}},
    )[0]["json"]
    existing = {
        "id": 3778,
        "sku": "B0BYTEST01",
        "attributes": [
            {
                "id": 9,
                "name": "Manual Color",
                "visible": True,
                "variation": False,
                "options": ["Bronze"],
            },
            {
                "name": "Runtime",
                "visible": True,
                "variation": False,
                "options": ["8 h"],
            },
        ],
        "meta_data": [
            {"key": "_kp_managed_attribute_names", "value": '["Runtime"]'}
        ],
    }
    published = _run_n8n_code(
        publish_code,
        nodes={"取数-上架包": package, "添加规格与Schema": added},
        input_json={"body": [existing]},
    )[0]["json"]

    assert published["method"] == "PUT"
    assert published["url"].endswith("/3778")
    assert published["woo_body"]["sku"] == "IGL-001"
    assert [item["name"] for item in published["woo_body"]["attributes"]] == [
        "Manual Color",
        "Luminous Flux",
    ]

    empty_package = {
        **package,
        "product": {
            "attributes": [],
            "structured_data": {"additional_property": []},
        },
    }
    emptied = _run_n8n_code(
        add_code,
        nodes={"取数-上架包": empty_package},
        input_json={"woo_body": {"sku": "IGL-001", "meta_data": []}},
    )[0]["json"]
    cleared = _run_n8n_code(
        publish_code,
        nodes={"取数-上架包": empty_package, "添加规格与Schema": emptied},
        input_json={"body": [existing]},
    )[0]["json"]
    assert [item["name"] for item in cleared["woo_body"]["attributes"]] == [
        "Manual Color"
    ]
