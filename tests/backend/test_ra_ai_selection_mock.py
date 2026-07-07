from __future__ import annotations

from r_system_v2.ra.ai_selection_mock import (
    MOCK_PIPELINE_VERSION,
    _evaluate_mock_layers,
    _final_decision,
)


def test_ra_mock_multi_ai_pipeline_uses_local_model_roles_only() -> None:
    context = {
        "candidate_id": "candidate-1",
        "asin": "B0MOCKAI01",
        "product": {
            "asin": "B0MOCKAI01",
            "title": "Camping Folding Chair",
            "title_zh": "露营折叠椅",
            "category": "Sports & Outdoors",
            "price": 39.99,
            "bsr": 2400,
            "reviews": 180,
            "seller_count": 6,
            "rating": 4.5,
            "lithium_battery_warning": False,
            "features": {
                "monthly_sales": 620,
                "fba_fee_usd": 6.2,
                "image_candidates": ["https://example.test/B0MOCKAI01.jpg"],
            },
        },
        "profit": {
            "verdict": "pass",
            "gross_profit_usd": 12.34,
            "gross_margin": 0.31,
        },
        "supplier": {
            "supplier_name": "露营椅源头工厂",
            "unit_price_cny": 42.0,
            "moq": 1,
            "match_score": 91,
            "one_piece_hint": True,
        },
    }

    layers = _evaluate_mock_layers(context)
    final = _final_decision(context, layers, channel="amazon")

    assert [layer.layer for layer in layers] == ["deepseek", "gpt", "opus"]
    assert all(layer.model_name.startswith("mock-") for layer in layers)
    assert all(layer.payload["mock"] is True for layer in layers)
    assert all(layer.payload["mock_pipeline_version"] == MOCK_PIPELINE_VERSION for layer in layers)
    assert all(layer.payload["skill_version"] == "v1" for layer in layers)
    assert all(len(layer.payload["skill_hash"]) == 64 for layer in layers)
    assert all(layer.payload["skill"]["file_keys"] == ["skill", "amazon", "shared"] for layer in layers)
    assert final["mock_pipeline_version"] == MOCK_PIPELINE_VERSION
    assert final["skill_version"] == "v1"
    assert len(final["skill_hash"]) == 64
    assert final["verdict"] in {"pass", "review"}
    assert final["final_score"] >= 58


def test_ra_mock_multi_ai_pipeline_stops_when_deepseek_rejects() -> None:
    context = {
        "candidate_id": "candidate-2",
        "asin": "B0MOCKAI02",
        "product": {
            "asin": "B0MOCKAI02",
            "title": "Unknown Ultra Cheap Crowded Product",
            "title_zh": "低价红海产品",
            "category": "Generic",
            "price": 9.99,
            "bsr": 250000,
            "reviews": 8000,
            "seller_count": 45,
            "rating": 3.6,
            "features": {"monthly_sales": 0},
        },
        "profit": {},
        "supplier": {},
    }

    layers = _evaluate_mock_layers(context)
    final = _final_decision(context, layers, channel="amazon")

    assert [layer.layer for layer in layers] == ["deepseek"]
    assert layers[0].verdict == "reject"
    assert final["verdict"] == "reject"
    assert "未进入 GPT/Opus" in final["decision_reason"]
