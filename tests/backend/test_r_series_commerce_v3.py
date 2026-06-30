from __future__ import annotations

import json

import pytest

from r_series.runtime.commerce_v3 import (
    LOCKED_ORGANIZATION_ID,
    REQUIRED_V3_SKILLS,
    RCommerceV3Engine,
    RCommerceV3Error,
)


def _engine(tmp_path):
    return RCommerceV3Engine(
        database_path=tmp_path / "r_products_v3.jsonl",
        report_path=tmp_path / "R_SERIES_V3_COMMERCE_REPORT.json",
        production_report_path=tmp_path
        / "R_SERIES_V3_PRODUCTION_DEPLOYMENT_REPORT.json",
        review_log_path=tmp_path / "r_review_logs_v3.jsonl",
    )


def test_r_commerce_v3_generates_success_products_without_api_keys(tmp_path):
    report = _engine(tmp_path).run_task(
        {
            "main_keyword": "portable door draft stopper",
            "category": "home improvement",
            "market": "Both",
            "price_range": "19-39",
            "target_count": 3,
            "task_budget_usd": 0.01,
        }
    )

    assert report["provider_mode"] == "mock"
    assert report["api_key_dependency"] is False
    assert report["organization_id"] == LOCKED_ORGANIZATION_ID
    assert report["budget_usage"]["organization_id"] == LOCKED_ORGANIZATION_ID
    assert set(REQUIRED_V3_SKILLS).issubset(set(report["required_skills"]))
    assert report["budget_usage"]["crawl_budget"] == 10
    assert report["budget_usage"]["stop_reason"] == "target_count_reached"
    assert len(report["selected_products"]) == 3

    for product in report["selected_products"]:
        assert product["organization_id"] == LOCKED_ORGANIZATION_ID
        assert product["main_keyword"]
        assert product["market"] in {"Amazon", "独立站", "Both"}
        assert product["channel_recommendation"] in {"amazon", "site", "dual"}
        assert 2 <= len(product["supplier_list"]) <= 5
        assert product["purchase_price_range"]
        assert product["selling_price"]
        assert product["size_weight"]
        assert product["reason"]["source"] == "deepseek_v4_pro"
        for supplier in product["supplier_list"]:
            assert supplier["organization_id"] == LOCKED_ORGANIZATION_ID
            assert supplier["supplier_name"]
            assert supplier["product_link"].startswith("https://mock.1688.local/")
            assert supplier["link"] == supplier["product_link"]
            assert supplier["preview_image"].startswith("data:image/svg+xml")
            assert "MOQ" in supplier
            assert "dropshipping_support" in supplier
            assert "moq_1_allowed" in supplier
            assert "sample_availability" in supplier
            assert supplier["shipping_origin"]

    assert all(
        supplier["organization_id"] == LOCKED_ORGANIZATION_ID
        for supplier in report["supplier_data"]
    )
    assert all(
        reason["organization_id"] == LOCKED_ORGANIZATION_ID
        for reason in report["reason_outputs"]
    )
    assert all(
        decision["organization_id"] == LOCKED_ORGANIZATION_ID
        for decision in report["decision_outputs"]
    )
    assert all(
        crawl_record["organization_id"] == LOCKED_ORGANIZATION_ID
        for crawl_record in report["crawl_records"]
    )


def test_r_commerce_v3_budget_stops_before_target(tmp_path):
    report = _engine(tmp_path).run_task(
        {
            "main_keyword": "desk cable organizer",
            "category": "office",
            "market": "Amazon",
            "price_range": "15-28",
            "target_count": 5,
            "task_budget_usd": 0.001,
        }
    )

    assert report["crawl_count"] == 1
    assert report["budget_usage"]["crawl_budget"] == 1
    assert report["budget_usage"]["stop_reason"] == "budget_exhausted"
    assert len(report["selected_products"]) <= 1


def test_r_commerce_v3_review_save_is_append_only_jsonl(tmp_path):
    engine = _engine(tmp_path)
    report = engine.run_task(
        {
            "main_keyword": "cabinet door bumper",
            "category": "hardware",
            "market": "独立站",
            "price_range": "12-24",
            "target_count": 1,
            "task_budget_usd": 0.01,
        }
    )
    product = report["selected_products"][0]

    first = engine.review_product(action="Save", product=product, reviewer="tester")
    second = engine.review_product(action="Save", product=product, reviewer="tester")

    assert first["status"] == "saved"
    assert second["status"] == "saved"
    assert first["log"]["organization_id"] == LOCKED_ORGANIZATION_ID
    rows = [
        json.loads(line)
        for line in (tmp_path / "r_products_v3.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 2
    assert rows[0]["organization_id"] == LOCKED_ORGANIZATION_ID
    assert rows[0]["product"]["candidate_id"] == product["candidate_id"]
    assert rows[0]["product"]["organization_id"] == LOCKED_ORGANIZATION_ID
    assert rows[1]["product"]["candidate_id"] == product["candidate_id"]


def test_r_commerce_v3_production_deployment_report(tmp_path):
    engine = _engine(tmp_path)

    report = engine.production_deployment_report()

    assert report["system_status"]["engine"] == "R_ENGINE_V3"
    assert report["system_status"]["production_ready"] is True
    assert report["org_lock_status"]["organization_id"] == LOCKED_ORGANIZATION_ID
    assert report["org_lock_status"]["org_isolation_enforced"] is True
    assert report["storage_status"]["initialized"] is True
    assert report["readiness_for_key_binding"]["ready"] is True
    assert report["readiness_for_key_binding"]["api_keys_configured"] is False
    assert all(status["loaded"] for status in report["skill_status"].values())
    assert (tmp_path / "r_products_v3.jsonl").exists()
    assert (tmp_path / "R_SERIES_V3_PRODUCTION_DEPLOYMENT_REPORT.json").exists()


def test_r_commerce_v3_requires_task_budget(tmp_path):
    with pytest.raises(RCommerceV3Error):
        _engine(tmp_path).run_task({"main_keyword": "desk organizer"})
