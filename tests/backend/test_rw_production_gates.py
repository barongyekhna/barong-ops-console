import gzip
import json

import pytest

from backend.app.api.routes.rw import _user_has_rw_role_access
from backend.app.models.user import User
from r_system_v2.rw.ai.deepseek_screening import DeepSeekScreeningSkill
from r_system_v2.rw.category.category_tree import (
    apply_selected_categories,
    is_holiday_category_id,
    load_category_tree,
    runnable_selected_category_ids,
)
from r_system_v2.rw.core.rule_engine import RuleEngine
from r_system_v2.rw.core.warehouse_engine import WarehouseEngine
from r_system_v2.rw.providers.keepa_provider import (
    MAX_REQUESTS_PER_MINUTE,
    MIN_PRODUCT_FINDER_PER_PAGE,
    MOCK_MODE,
    USE_REAL_KEEPA_API,
    KeepaConfigurationError,
    KeepaProvider,
    KeepaResponseError,
    _default_http_get_json,
    _parse_discovery_payload,
    _parse_product_payload,
)
from r_system_v2.rw.scheduler.keepa_scheduler import KeepaScheduler
from r_system_v2.rw.storage.repository import MockWarehouseRepository


def test_keepa_provider_defaults_to_production_without_mock_fallback(monkeypatch):
    monkeypatch.delenv("KEEPA_API_KEY", raising=False)

    provider = KeepaProvider()

    assert MOCK_MODE is False
    assert USE_REAL_KEEPA_API is True
    assert provider.mock_mode is False
    with pytest.raises(KeepaConfigurationError, match="keepa_api_key_missing"):
        provider.status()


def test_keepa_http_get_json_decodes_gzip_response(monkeypatch):
    class Response:
        headers = {"Content-Encoding": "gzip"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return gzip.compress(b'{"tokensLeft": 12, "refillIn": 0}')

    def fake_urlopen(request, timeout):
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Accept-encoding"] == "identity"
        assert timeout == 3.0
        return Response()

    monkeypatch.setattr(
        "r_system_v2.rw.providers.keepa_provider.urlopen",
        fake_urlopen,
    )

    assert _default_http_get_json(
        "https://api.keepa.com/token",
        {"key": "hidden"},
        3.0,
    ) == {"tokensLeft": 12, "refillIn": 0}


def test_keepa_product_parser_uses_stats_for_reviews_sellers_and_rating():
    product = _parse_product_payload(
        {
            "products": [
                {
                    "asin": "B012345678",
                    "title": "Compact Storage Basket",
                    "brand": "Fixture",
                    "stats": {
                        "current": [
                            -1,
                            3499,
                            -1,
                            4200,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            -1,
                            6,
                            -1,
                            -1,
                            -1,
                            -1,
                            46,
                            318,
                        ]
                    },
                    "imagesCSV": "test-image.jpg",
                    "categoryTree": [{"name": "Home & Kitchen"}],
                }
            ]
        },
        asin="B012345678",
        source_query="test",
    )

    assert product.reviews == 318
    assert product.seller_count == 6
    assert product.rating == 4.6
    assert product.image_url == "https://images-na.ssl-images-amazon.com/images/I/test-image.jpg"
    assert "https://m.media-amazon.com/images/I/test-image.jpg" in product.image_candidates


def test_keepa_product_parser_extracts_fba_fee_and_fee_inputs():
    product = _parse_product_payload(
        {
            "products": [
                {
                    "asin": "B0FBAFEE01",
                    "title": "Outdoor Tool Organizer",
                    "brand": "Fixture",
                    "newPrice": 3299,
                    "salesRank": 4500,
                    "reviewCount": 80,
                    "sellerCount": 5,
                    "categoryTree": [{"name": "Patio, Lawn & Garden", "catId": 2972638011}],
                    "fbaFees": {"pickAndPackFee": 476, "lastUpdate": 8153992},
                    "referralFeePercentage": 15.01,
                    "packageWeight": 449,
                    "packageLength": 226,
                    "packageWidth": 163,
                    "packageHeight": 61,
                    "itemWeight": 410,
                }
            ]
        },
        asin="B0FBAFEE01",
        source_query="test",
    )

    assert product.fba_fee_usd == 4.76
    assert product.fba_fee_last_update == 8153992
    assert product.referral_fee_percentage == 15.01
    assert product.package_weight_g == 449
    assert product.package_length_mm == 226
    assert product.package_width_mm == 163
    assert product.package_height_mm == 61
    assert product.item_weight_g == 410


def test_keepa_product_parser_uses_avg90_and_bsr_features_when_current_missing():
    current = [-1] * 18
    current[1] = 2999
    current[3] = 4400
    avg90 = [-1] * 18
    avg90[11] = 8
    avg90[16] = 45
    avg90[17] = 222

    product = _parse_product_payload(
        {
            "products": [
                {
                    "asin": "B012345678",
                    "title": "Compact Storage Basket",
                    "brand": "Fixture",
                    "stats": {"current": current, "avg90": avg90},
                    "salesRanks": {
                        "1055398": [[1, 1200]],
                        "13679381": [[1, 4400]],
                    },
                    "monthlySold": 320,
                    "categoryTree": [
                        {"name": "Home & Kitchen", "catId": 1055398},
                        {"name": "Storage", "catId": 13679381},
                    ],
                }
            ]
        },
        asin="B012345678",
        source_query="test",
    )

    assert product.reviews == 222
    assert product.seller_count == 8
    assert product.rating == 4.5
    assert product.monthly_sales == 320
    assert product.parent_category_rank == 1200
    assert product.subcategory_rank == 4400
    assert product.category == "Storage"
    assert product.category_id == "13679381"
    assert product.category_path == ["Home & Kitchen", "Storage"]
    assert product.category_id_path == ["1055398", "13679381"]


def test_keepa_product_parser_does_not_fake_missing_subcategory_rank():
    current = [-1] * 18
    current[1] = 2999
    current[3] = 4400

    product = _parse_product_payload(
        {
            "products": [
                {
                    "asin": "B012345678",
                    "title": "Compact Storage Basket",
                    "brand": "Fixture",
                    "stats": {"current": current},
                    "salesRanks": {"1055398": [[1, 1200]]},
                    "categoryTree": [
                        {"name": "Home & Kitchen", "catId": 1055398},
                        {"name": "Storage", "catId": 13679381},
                    ],
                }
            ]
        },
        asin="B012345678",
        source_query="test",
    )

    assert product.bsr == 4400
    assert product.parent_category_rank == 1200
    assert product.subcategory_rank is None


def test_keepa_product_parser_ignores_monthly_sales_history_timestamps():
    product = _parse_product_payload(
        {
            "products": [
                {
                    "asin": "B012345678",
                    "title": "Compact Storage Basket",
                    "brand": "Fixture",
                    "stats": {"current": [-1, 3499, -1, 4200]},
                    "monthlySoldHistory": [7_900_000, 120, 7_900_120, 300],
                    "categoryTree": [{"name": "Home & Kitchen"}],
                }
            ]
        },
        asin="B012345678",
        source_query="test",
    )

    assert product.monthly_sales == 300


def test_keepa_product_parser_marks_missing_monthly_sales_unknown():
    product = _parse_product_payload(
        {
            "products": [
                {
                    "asin": "B012345678",
                    "title": "Compact Storage Basket",
                    "brand": "Fixture",
                    "stats": {"current": [-1, 3499, -1, 4200]},
                    "categoryTree": [{"name": "Home & Kitchen"}],
                }
            ]
        },
        asin="B012345678",
        source_query="test",
    )

    assert product.monthly_sales is None


def test_keepa_discovery_pushes_hard_rules_into_product_finder_selection():
    captured_selection: dict[str, object] = {}

    def fake_http_get_json(url, params, timeout):
        assert url.endswith("/query")
        assert timeout == 10.0
        captured_selection.update(json.loads(str(params["selection"])))
        return {"asinList": ["B012345678"]}

    provider = KeepaProvider(api_key="test-key", http_get_json=fake_http_get_json)

    assert provider.discover_asins(category_id="1055398", limit=20) == ["B012345678"]
    assert captured_selection["current_NEW_gte"] == 2500
    assert captured_selection["current_NEW_lte"] <= 7000
    assert captured_selection["current_SALES_gte"] >= 1
    assert captured_selection["current_SALES_lte"] <= 50000
    assert captured_selection["current_COUNT_NEW_lte"] == 15
    assert captured_selection["current_COUNT_REVIEWS_lte"] == 500
    assert captured_selection["perPage"] == MIN_PRODUCT_FINDER_PER_PAGE


def test_keepa_discovery_segments_product_finder_pages():
    captured: list[dict[str, object]] = []

    def fake_http_get_json(url, params, timeout):
        del timeout
        assert url.endswith("/query")
        selection = json.loads(str(params["selection"]))
        captured.append(selection)
        return {"asinList": ["B012345678"]}

    provider = KeepaProvider(api_key="test-key", http_get_json=fake_http_get_json)

    provider.discover_asins(category_id="1055398", limit=20, page=0)
    provider.discover_asins(category_id="1055398", limit=20, page=1)
    provider.discover_asins(category_id="1055398", limit=20, page=9)

    assert captured[0]["current_NEW_gte"] == 2500
    assert captured[0]["current_NEW_lte"] == 3500
    assert captured[0]["current_SALES_gte"] == 1
    assert captured[0]["current_SALES_lte"] == 5000
    assert captured[0]["page"] == 0
    assert captured[1]["current_NEW_gte"] == 2500
    assert captured[1]["current_SALES_gte"] == 5001
    assert captured[1]["page"] == 0
    assert captured[2]["current_NEW_gte"] == 2500
    assert captured[2]["current_SALES_gte"] == 1
    assert captured[2]["page"] == 1


def test_keepa_discovery_does_not_use_unfiltered_bestseller_fallback():
    called_urls: list[str] = []

    def fake_http_get_json(url, params, timeout):
        del params, timeout
        called_urls.append(url)
        raise RuntimeError("query failed")

    provider = KeepaProvider(api_key="test-key", http_get_json=fake_http_get_json)

    with pytest.raises(KeepaResponseError):
        provider.discover_asins(category_id="1055398", limit=20)
    assert [url.rsplit("/", 1)[-1] for url in called_urls] == ["query"]


def test_keepa_discovery_empty_result_advances_without_blocking_category():
    assert _parse_discovery_payload({"totalResults": 0}, limit=20) == []
    assert _parse_discovery_payload({"asinList": []}, limit=20) == []
    with pytest.raises(KeepaResponseError, match="keepa_query_error"):
        _parse_discovery_payload({"error": {"message": "bad selection"}}, limit=20)


def test_holiday_categories_are_runnable_and_use_sales_only_discovery():
    captured_selection: dict[str, object] = {}

    def fake_http_get_json(url, params, timeout):
        del timeout
        assert url.endswith("/query")
        captured_selection.update(json.loads(str(params["selection"])))
        return {"asinList": ["B087654321"]}

    payload = apply_selected_categories(load_category_tree(), ["holiday-products"])
    runnable = runnable_selected_category_ids(payload)
    provider = KeepaProvider(api_key="test-key", http_get_json=fake_http_get_json)

    assert "holiday-christmas" in runnable
    assert is_holiday_category_id("holiday-christmas") is True
    assert provider.discover_asins(category_id="holiday-christmas", limit=20) == ["B087654321"]
    assert "title" in captured_selection
    assert "current_NEW_gte" not in captured_selection
    assert captured_selection["perPage"] == MIN_PRODUCT_FINDER_PER_PAGE


def test_keepa_scheduler_caps_requests_at_twenty_without_burst():
    provider = KeepaProvider(force_mock=True, tokens_per_min=200)
    repository = MockWarehouseRepository()
    engine = WarehouseEngine(provider=provider, rule_engine=RuleEngine(), repository=repository)
    records = engine.ingest([f"B0TEST{i:04d}" for i in range(30)])
    scheduler = KeepaScheduler(
        provider=provider,
        processor=engine.process_discovered_asin,
        rate_limit_per_min=200,
    )

    scheduler.enqueue(records)
    report = scheduler.run_once()

    assert report.rate_limit_per_min == MAX_REQUESTS_PER_MINUTE
    assert report.token_budget == MAX_REQUESTS_PER_MINUTE
    assert report.processed == MAX_REQUESTS_PER_MINUTE
    assert report.no_burst_mode is True
    assert report.queue_based_ingestion is True
    assert report.refill_aware is True


def test_deepseek_skill_loads_and_emits_strict_json_for_rule_passed_product():
    provider = KeepaProvider(force_mock=True)
    repository = MockWarehouseRepository()
    engine = WarehouseEngine(
        provider=provider,
        rule_engine=RuleEngine(),
        repository=repository,
        deepseek_skill=DeepSeekScreeningSkill(),
    )
    record = engine.ingest("portable door draft stopper")[0]

    result = engine.process_discovered_asin(record)

    assert result.rule_evaluation.passed is True
    assert result.deepseek_screening is not None
    assert result.deepseek_screening.skill_loaded is True
    assert result.deepseek_screening.quant_filter_enabled is True
    assert result.deepseek_screening.rule_based_scoring_active is True
    assert result.deepseek_screening.output_schema_strict_json is True
    assert set(result.deepseek_screening.strict_json) == {
        "score",
        "verdict",
        "competition_attackability",
        "demand_quality",
        "top_reason",
        "channel_guess",
    }
    assert repository.ai_evaluations
    assert result.transitions[:3] == ["discovered", "enriched", "rule_passed"]
    assert result.transitions[-1] == "ai1_passed"


def test_rw_role_gate_allows_only_owner_and_super_admin():
    assert _user_has_rw_role_access(User(username="owner", role="owner")) is True
    assert (
        _user_has_rw_role_access(User(username="super_admin", role="super_admin"))
        is True
    )
    assert (
        _user_has_rw_role_access(User(username="normal_user", role="normal_user"))
        is False
    )
