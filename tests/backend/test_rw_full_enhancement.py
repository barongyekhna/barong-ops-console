from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.app.api.routes.rw import rw_category_save, rw_category_select
from r_system_v2.rw.ai.model_config import rw_deepseek_model
from r_system_v2.rw.category.category_tree import (
    generate_category_tree_from_amazon_doc,
    runnable_selected_category_ids,
    select_category,
    selected_category_ids,
)
from r_system_v2.rw.core.models import (
    IngestionRecord,
    KeepaProductData,
    NormalizedProduct,
    ProductState,
)
from r_system_v2.rw.core.rule_engine import RuleEngine
from r_system_v2.rw.core.warehouse_engine import WarehouseEngine
from r_system_v2.rw.ai.deepseek_screening import (
    DeepSeekScreeningSkill,
    deepseek_reject_code,
)
from r_system_v2.rw.processor.feature_extractor import extract_product_features
from r_system_v2.rw.processor.monthly_sales_estimator import estimate_monthly_sales
from r_system_v2.rw.providers.keepa_provider import KeepaProvider
from r_system_v2.rw.scoring_engine import ScoringEngine
from r_system_v2.rw.scheduler.category_rate_limiter import CategoryRateLimiter
from r_system_v2.rw.scheduler.category_scheduler import CategoryScheduler
from r_system_v2.rw.scheduler.keepa_scheduler import KeepaScheduler
from r_system_v2.rw.skill_metadata import load_deepseek_skill_metadata
from r_system_v2.rw.storage.repository import MockWarehouseRepository
from r_system_v2.rw.storage.runtime_settings import (
    load_runtime_settings,
    save_runtime_settings,
)
from r_system_v2.rw.storage.discovery_state import (
    load_discovery_cursor,
    save_discovery_cursor,
)
from r_system_v2.rw.storage.pipeline_events import release_queue_failures


def test_category_tree_parent_cascades_but_child_selection_is_local(tmp_path):
    doc_path = tmp_path / "amazon.md"
    tree_path = tmp_path / "category_tree.json"
    doc_path.write_text("避开: 锂电 / restricted / IP / 易碎", encoding="utf-8")

    generate_category_tree_from_amazon_doc(doc_path=doc_path, output_path=tree_path)
    parent_off = select_category("1055398", False, path=tree_path)
    assert "1055398" not in selected_category_ids(parent_off)
    assert "13679381" not in selected_category_ids(parent_off)

    parent_on = select_category("1055398", True, path=tree_path)
    assert "1055398" in selected_category_ids(parent_on)
    assert "13679381" in selected_category_ids(parent_on)
    assert "1055398" not in runnable_selected_category_ids(parent_on)
    assert "13679381" in runnable_selected_category_ids(parent_on)

    child_off = select_category("172574", False, path=tree_path)
    assert "1064954" in selected_category_ids(child_off)
    assert "172574" not in selected_category_ids(child_off)


def test_rw_category_select_preview_does_not_persist_runtime_settings():
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    db = Session()
    db.execute(
        text(
            """
            CREATE TABLE rw_runtime_settings (
              key TEXT PRIMARY KEY,
              value TEXT,
              updated_at TEXT
            )
            """
        )
    )
    save_runtime_settings(db, {"selected_categories": ["1055398"]})
    db.commit()

    result = rw_category_select(
        {"category_id": "172574", "selected": False},
        db=db,
        user=object(),  # route deletes user after dependency authorization
    )
    persisted = load_runtime_settings(db)

    assert "172574" not in result["selected_categories"]
    assert persisted.selected_categories == ["1055398"]


def test_rw_category_save_persists_user_selection_not_runnable_projection():
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    db = Session()
    db.execute(
        text(
            """
            CREATE TABLE rw_runtime_settings (
              key TEXT PRIMARY KEY,
              value TEXT,
              updated_at TEXT
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE enrich_queue (
              asin TEXT PRIMARY KEY,
              marketplace TEXT,
              source_query TEXT,
              category_id TEXT,
              category_path TEXT,
              picked BOOLEAN,
              retry_count INTEGER,
              last_error TEXT,
              enqueued_at TEXT,
              picked_at TEXT
            )
            """
        )
    )

    result = rw_category_save(
        {"selected_categories": ["1055398", "284507", "16510975011"]},
        db=db,
        user=object(),
    )
    persisted = load_runtime_settings(db)

    assert result["selected_categories"] == ["1055398", "284507", "16510975011"]
    assert result["selected_count"] == 3
    assert result["runnable_selected_categories"] == ["284507", "16510975011"]
    assert result["runnable_selected_count"] == 2
    assert persisted.selected_categories == ["1055398", "284507", "16510975011"]


def test_keepa_discovery_cursor_persists_in_runtime_settings():
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    db = Session()
    db.execute(
        text(
            """
            CREATE TABLE rw_runtime_settings (
              key TEXT PRIMARY KEY,
              value TEXT,
              updated_at TEXT
            )
            """
        )
    )

    assert load_discovery_cursor(db, "3400371") == 0
    save_discovery_cursor(db, "3400371", 17)
    db.commit()

    assert load_discovery_cursor(db, "3400371") == 17
    assert load_discovery_cursor(db, "553844") == 0


def test_rw_deepseek_model_defaults_to_pro_and_prefers_rw_override(monkeypatch):
    monkeypatch.delenv("RW_DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    assert rw_deepseek_model() == "deepseek-v4-pro"

    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("RW_DEEPSEEK_MODEL", "deepseek-v4-pro")
    assert rw_deepseek_model() == "deepseek-v4-pro"


def test_deepseek_rejects_edible_products_before_ra_review():
    product = NormalizedProduct(
        asin="B0FOODTEST",
        source_query="keepa_category:pet-food",
        marketplace="US",
        title="Chicken Flavor Dog Treats with Vitamins",
        brand="Pet Pantry",
        category="Pet Food",
        price=29.99,
        bsr=1200,
        reviews=86,
        seller_count=4,
        landed_cost=None,
        est_net_margin=None,
        brand_share=0.12,
        price_trend="stable",
        rating=4.6,
        features={"monthly_sales": 800},
    )

    screening = DeepSeekScreeningSkill().evaluate(product)
    decision = ScoringEngine().score_deepseek(screening)

    assert screening.verdict == "cut"
    assert screening.score == 0
    assert decision.action == "reject"
    assert "食品" in decision.reason


def test_deepseek_does_not_reject_food_processing_appliance_as_edible_product():
    product = NormalizedProduct(
        asin="B0FHJ4Q436",
        source_query="keepa_category:284507",
        marketplace="US",
        title=(
            "Turelar Immersion Blender Handheld 1100W - 3 in 1 Hand Blenders "
            "Set with Trigger Speed Control Emulsion Stick with Whisk and Milk "
            "Frother, Emulsifier for Kitchen for Soup, Smoothie, Puree"
        ),
        brand="Turelar",
        category="Hand Blenders",
        price=29.99,
        bsr=1,
        reviews=64,
        seller_count=3,
        landed_cost=None,
        est_net_margin=None,
        brand_share=0.12,
        price_trend="stable",
        rating=4.5,
        features={
            "amazon_category_path": [
                "Home & Kitchen",
                "Kitchen & Dining",
                "Small Appliances",
                "Blenders",
                "Hand Blenders",
            ],
            "monthly_sales": 800,
            "monthly_sales_estimate": 800,
            "subcategory_name": "Hand Blenders",
        },
    )

    screening = DeepSeekScreeningSkill().evaluate(product)

    assert screening.verdict != "cut"


def test_deepseek_does_not_reject_bakery_coffee_shop_label_printer_as_food():
    product = NormalizedProduct(
        asin="B0GT48P7NT",
        source_query="keepa_category:172574",
        marketplace="US",
        title=(
            "NIIMBOT B2 Label Maker Machine with Tape, Portable Bluetooth 2Inch "
            "Label Printer with Multiple Templates, Thermal Labeler for Home Kitchen "
            "Office Coffee Shop Bakery Organization, Gray White"
        ),
        brand="NIIMBOT",
        category="Portable Thermal Printers",
        price=39.99,
        bsr=34,
        reviews=120,
        seller_count=3,
        landed_cost=None,
        est_net_margin=None,
        brand_share=0.12,
        price_trend="stable",
        rating=4.5,
        features={
            "amazon_category_path": [
                "Office Products",
                "Office Electronics",
                "Printers & Accessories",
                "Printers",
                "Portable Thermal Printers",
            ],
            "monthly_sales": 50,
            "monthly_sales_estimate": 50,
            "subcategory_name": "Portable Thermal Printers",
            "parent_category_name": "Office Products",
        },
    )

    screening = DeepSeekScreeningSkill().evaluate(product)

    assert not (
        screening.verdict == "cut"
        and screening.score == 0
        and "食品" in screening.top_reason
    )


def test_deepseek_does_not_reject_baking_pan_as_edible_product():
    product = NormalizedProduct(
        asin="B0FCBF2X4H",
        source_query="keepa_category:289668",
        marketplace="US",
        title=(
            "Nonstick Baking Pan Set Cookie Sheet Bakeware Oven Tray for "
            "Kitchen Bakery Cake Bread Roasting"
        ),
        brand="BakeMate",
        category="Bakeware",
        price=29.99,
        bsr=2500,
        reviews=140,
        seller_count=5,
        landed_cost=None,
        est_net_margin=None,
        brand_share=0.12,
        price_trend="stable",
        rating=4.5,
        features={
            "amazon_category_path": [
                "Home & Kitchen",
                "Kitchen & Dining",
                "Bakeware",
                "Baking Pans",
            ],
            "monthly_sales": 600,
            "monthly_sales_estimate": 600,
            "subcategory_name": "Baking Pans",
            "parent_category_name": "Home & Kitchen",
        },
    )

    screening = DeepSeekScreeningSkill().evaluate(product)

    assert not (
        screening.verdict == "cut"
        and screening.score == 0
        and "食品" in screening.top_reason
    )


def test_deepseek_still_rejects_real_coffee_product_as_edible():
    product = NormalizedProduct(
        asin="B0COFFEE01",
        source_query="keepa_category:grocery",
        marketplace="US",
        title="Ground Coffee Beans Medium Roast Breakfast Blend",
        brand="RoastCo",
        category="Grocery & Gourmet Food",
        price=29.99,
        bsr=900,
        reviews=90,
        seller_count=4,
        landed_cost=None,
        est_net_margin=None,
        brand_share=0.12,
        price_trend="stable",
        rating=4.6,
        features={
            "amazon_category_path": [
                "Grocery & Gourmet Food",
                "Beverages",
                "Coffee",
            ],
            "monthly_sales": 800,
        },
    )

    screening = DeepSeekScreeningSkill().evaluate(product)

    assert screening.verdict == "cut"
    assert screening.score == 0
    assert "食品" in screening.top_reason or "饮品" in screening.top_reason


def test_deepseek_rejects_pest_control_products_before_ra_review():
    product = NormalizedProduct(
        asin="B0BUGZAPER",
        source_query="keepa_category:pest-control",
        marketplace="US",
        title="Outdoor Mosquito Killer Lamp and Bug Zapper for Patio",
        brand="BugStop",
        category="Pest Control",
        price=39.99,
        bsr=2400,
        reviews=96,
        seller_count=5,
        landed_cost=None,
        est_net_margin=None,
        brand_share=0.16,
        price_trend="stable",
        rating=4.2,
        features={"monthly_sales_estimate": 500},
    )

    screening = DeepSeekScreeningSkill().evaluate(product)
    decision = ScoringEngine().score_deepseek(screening)

    assert screening.verdict == "cut"
    assert screening.score == 0
    assert decision.action == "reject"
    assert "杀虫" in screening.top_reason or "灭虫" in screening.top_reason
    assert deepseek_reject_code(screening.top_reason) == "deepseek_pest_control_product"


def test_deepseek_does_not_reject_non_insect_animal_repellent_as_pest_control():
    product = NormalizedProduct(
        asin="B0DEERTEST",
        source_query="keepa_category:garden",
        marketplace="US",
        title="Outdoor Deer and Rabbit Repellent for Garden Plants",
        brand="GardenGuard",
        category="Patio, Lawn & Garden",
        price=29.99,
        bsr=5200,
        reviews=88,
        seller_count=5,
        landed_cost=None,
        est_net_margin=None,
        brand_share=0.16,
        price_trend="stable",
        rating=4.1,
        features={
            "monthly_sales_estimate": 420,
            "parent_category_name": "Patio, Lawn & Garden",
            "subcategory_name": "Beneficial Insects",
        },
    )

    screening = DeepSeekScreeningSkill().evaluate(product)

    assert screening.verdict != "cut"


def test_deepseek_rejects_liquid_powder_and_spray_content_before_ra_review():
    from r_system_v2.rw.ai.deepseek_screening import _restricted_form_reject_reason

    # Ambiguous categories route to a real DeepSeek form confirmation; the
    # offline strong-phrase classifier stands in for the confirmed verdict.
    skill = DeepSeekScreeningSkill()
    offline_skill = DeepSeekScreeningSkill()
    skill._deepseek_form_reject = _restricted_form_reject_reason
    products = [
        NormalizedProduct(
            asin="B0LIQUID01",
            source_query="keepa_category:home",
            marketplace="US",
            title="Concentrated Liquid Cleaner Refill for Home Surfaces",
            brand="CleanCo",
            category="Household Cleaning",
            price=29.99,
            bsr=3200,
            reviews=90,
            seller_count=4,
            landed_cost=None,
            est_net_margin=None,
            brand_share=0.12,
            price_trend="stable",
            rating=4.3,
            features={"monthly_sales_estimate": 520},
        ),
        NormalizedProduct(
            asin="B0POWDER01",
            source_query="keepa_category:home",
            marketplace="US",
            title="Deodorizing Powder Refill for Storage and Closets",
            brand="FreshCo",
            category="Home Care",
            price=26.99,
            bsr=4100,
            reviews=110,
            seller_count=5,
            landed_cost=None,
            est_net_margin=None,
            brand_share=0.14,
            price_trend="stable",
            rating=4.2,
            features={"monthly_sales_estimate": 480},
        ),
        NormalizedProduct(
            asin="B0SPRAY001",
            source_query="keepa_category:home",
            marketplace="US",
            title="Room Spray Refill for Fabric and Air Freshening",
            brand="FreshAir",
            category="Home Fragrance",
            price=32.99,
            bsr=3800,
            reviews=130,
            seller_count=6,
            landed_cost=None,
            est_net_margin=None,
            brand_share=0.18,
            price_trend="stable",
            rating=4.4,
            features={"monthly_sales_estimate": 610},
        ),
    ]

    for product in products:
        screening = skill.evaluate(product)
        assert screening.verdict == "cut"
        assert screening.score == 0
        assert deepseek_reject_code(screening.top_reason) == (
            "deepseek_liquid_powder_spray_product"
        )
        # Without a DeepSeek confirmation (offline / no key), ambiguous
        # products must be kept for review — never blind keyword-cut.
        offline = offline_skill.evaluate(product)
        assert offline.verdict != "cut"


def test_rule_engine_leaves_liquid_form_policy_to_deepseek():
    product = NormalizedProduct(
        asin="B0RULELIQ1",
        source_query="keepa_category:home",
        marketplace="US",
        title="Concentrated Liquid Cleaner Refill for Home Surfaces",
        brand="CleanCo",
        category="Household Cleaning",
        price=29.99,
        bsr=3200,
        reviews=90,
        seller_count=4,
        landed_cost=None,
        est_net_margin=None,
        brand_share=0.12,
        price_trend="stable",
        rating=4.3,
        features={"monthly_sales_estimate": 520},
    )

    result = RuleEngine().evaluate(product)

    assert result.passed is True


def test_deepseek_does_not_reject_empty_spray_bottle_as_spray_content():
    product = NormalizedProduct(
        asin="B0BOTTLE01",
        source_query="keepa_category:home",
        marketplace="US",
        title="Empty Refillable Spray Bottle for Plants and Cleaning",
        brand="BottleCo",
        category="Home & Kitchen",
        price=25.99,
        bsr=6200,
        reviews=95,
        seller_count=5,
        landed_cost=None,
        est_net_margin=None,
        brand_share=0.12,
        price_trend="stable",
        rating=4.1,
        features={"monthly_sales_estimate": 390},
    )

    screening = DeepSeekScreeningSkill().evaluate(product)

    assert screening.verdict != "cut"


def test_deepseek_does_not_reject_spray_tools_or_usage_context_as_spray_content():
    product = NormalizedProduct(
        asin="B0HEATGUN1",
        source_query="keepa_category:tools",
        marketplace="US",
        title="Spraytech Heat Gun for Removing Paint and Adhesive",
        brand="ToolCo",
        category="Tools & Home Improvement",
        price=32.99,
        bsr=5200,
        reviews=140,
        seller_count=6,
        landed_cost=None,
        est_net_margin=None,
        brand_share=0.15,
        price_trend="stable",
        rating=4.4,
        features={"monthly_sales_estimate": 450},
    )

    screening = DeepSeekScreeningSkill().evaluate(product)

    assert screening.verdict != "cut"


def test_monthly_sales_estimator_prefers_keepa_truth_and_estimates_missing_values():
    real = estimate_monthly_sales(
        bsr=8_000,
        category="Home & Kitchen",
        monthly_sales=320,
    )
    estimated = estimate_monthly_sales(
        bsr=8_000,
        category="Home & Kitchen",
        parent_category_name="Home & Kitchen",
        subcategory_name="Storage",
    )

    assert real.estimate == 320
    assert real.minimum == 320
    assert real.maximum == 320
    assert real.source == "keepa_monthly_sold"
    assert real.confidence == "high"
    assert estimated.estimate > 0
    assert estimated.minimum <= estimated.estimate <= estimated.maximum
    assert estimated.source == "bsr_estimate_v2"
    assert estimated.confidence in {"medium", "low"}


def test_feature_extractor_adds_monthly_sales_estimate_for_missing_keepa_sales():
    product = extract_product_features(
        "keepa_category:13679381",
        KeepaProductData(
            asin="B0ESTIMATE1",
            marketplace="US",
            title="Portable Storage Basket",
            brand="Fixture",
            category="Home & Kitchen",
            price=34.99,
            bsr=8_000,
            reviews=120,
            seller_count=6,
            landed_cost=None,
            brand_share=0.18,
            price_trend="stable",
            monthly_sales=None,
            parent_category_name="Home & Kitchen",
            subcategory_name="Storage",
            subcategory_rank=8_000,
            fba_fee_usd=4.76,
            fba_fee_last_update=8153992,
            referral_fee_percentage=15.0,
            package_weight_g=449,
            package_length_mm=226,
            package_width_mm=163,
            package_height_mm=61,
            mock_generated=False,
        ),
    )

    assert product.features["monthly_sales"] is None
    assert product.features["monthly_sales_source"] == "bsr_estimate_v2"
    assert product.features["monthly_sales_estimate"] > 0
    assert product.features["monthly_sales_estimate_source"] == "bsr_estimate_v2"
    assert product.features["monthly_sales_confidence"] == "medium"
    assert product.features["fba_fee_usd"] == 4.76
    assert product.features["fba_fee_source"] == "keepa_fbaFees.pickAndPackFee"
    assert product.features["referral_fee_percentage"] == 15.0
    assert product.features["package_weight_g"] == 449


def test_category_rate_limiter_balances_twenty_categories_for_ten_minutes():
    categories = [f"category-{index:02d}" for index in range(20)]
    plan = CategoryRateLimiter().plan(categories, 10)
    payload = plan.to_dict()

    assert payload["total_rate_per_min"] == 20
    assert payload["total_batch"] == 200
    assert payload["no_overuse"] is True
    assert payload["no_starvation"] is True
    assert payload["balanced"] is True
    assert {item["window_total"] for item in payload["allocations"]} == {10}


def test_keepa_scheduler_enqueues_records_by_category_allocation():
    provider = KeepaProvider(force_mock=True)
    scheduler = KeepaScheduler(provider=provider, processor=lambda record: record)
    records_by_category = {
        "home-kitchen": [
            IngestionRecord(asin=f"B0HOME{index:04d}", source_query="home", category_id="home-kitchen")
            for index in range(25)
        ],
        "office-products": [
            IngestionRecord(asin=f"B0OFFI{index:04d}", source_query="office", category_id="office-products")
            for index in range(25)
        ],
    }

    plan = scheduler.enqueue_by_category(records_by_category, window_minutes=1)

    assert [allocation.window_total for allocation in plan.allocations] == [10, 10]
    assert len(scheduler.queue) == 20
    assert sum(1 for record in scheduler.queue if record.category_id == "home-kitchen") == 10
    assert sum(1 for record in scheduler.queue if record.category_id == "office-products") == 10


def test_category_scheduler_never_claims_processed_asins():
    engine = create_engine("sqlite:///:memory:")
    session_factory = sessionmaker(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE products_rw (asin TEXT PRIMARY KEY)"))
        connection.execute(
            text(
                """
                CREATE TABLE enrich_queue (
                  asin TEXT PRIMARY KEY,
                  marketplace TEXT,
                  source_query TEXT,
                  category_id TEXT,
                  category_path TEXT,
                  picked BOOLEAN,
                  retry_count INTEGER,
                  last_error TEXT,
                  enqueued_at TEXT,
                  picked_at TEXT
                )
                """
            )
        )
    scheduler = CategoryScheduler()
    with session_factory() as db:
        db.execute(text("INSERT INTO products_rw (asin) VALUES ('B0DONE0001')"))
        inserted = scheduler.enqueue_discovered(
            db,
            category_id="1055398",
            asins=["B0DONE0001", "B0NEW00001"],
        )
        db.execute(
            text(
                """
                INSERT INTO enrich_queue (
                  asin, marketplace, source_query, category_id,
                  category_path, picked, retry_count, enqueued_at
                )
                VALUES (
                  'B0DONE0002', 'US', 'keepa_category:1055398', '1055398',
                  '1055398', false, 0, CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.execute(text("INSERT INTO products_rw (asin) VALUES ('B0DONE0002')"))
        records, report = scheduler.claim(
            db,
            selected_categories=["1055398"],
            requested_tokens=20,
        )

    assert inserted == 1
    assert [record.asin for record in records] == ["B0NEW00001"]
    assert report.claimed == 1


def test_category_scheduler_fills_unused_tokens_from_other_selected_queues():
    engine = create_engine("sqlite:///:memory:")
    session_factory = sessionmaker(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE products_rw (asin TEXT PRIMARY KEY)"))
        connection.execute(
            text(
                """
                CREATE TABLE enrich_queue (
                  asin TEXT PRIMARY KEY,
                  marketplace TEXT,
                  source_query TEXT,
                  category_id TEXT,
                  category_path TEXT,
                  picked BOOLEAN,
                  retry_count INTEGER,
                  last_error TEXT,
                  enqueued_at TEXT,
                  picked_at TEXT
                )
                """
            )
        )
    scheduler = CategoryScheduler()
    selected_categories = [f"cat-{index:02d}" for index in range(40)]
    with session_factory() as db:
        scheduler.enqueue_discovered(
            db,
            category_id="cat-39",
            asins=["B0FILL0001", "B0FILL0002"],
        )
        records, report = scheduler.claim(
            db,
            selected_categories=selected_categories,
            requested_tokens=20,
        )

    assert [record.asin for record in records] == ["B0FILL0001", "B0FILL0002"]
    assert report.claimed == 2


def test_queue_failures_dead_letter_non_transient_errors_after_retry_limit():
    engine = create_engine("sqlite:///:memory:")
    session_factory = sessionmaker(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE enrich_queue (
                  asin TEXT PRIMARY KEY,
                  marketplace TEXT,
                  source_query TEXT,
                  category_id TEXT,
                  category_path TEXT,
                  picked BOOLEAN,
                  retry_count INTEGER,
                  last_error TEXT,
                  enqueued_at TEXT,
                  picked_at TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO enrich_queue (
                  asin, marketplace, source_query, category_id,
                  category_path, picked, retry_count, enqueued_at, picked_at
                )
                VALUES (
                  'B0FAIL0001', 'US', 'keepa_category:holiday-halloween',
                  'holiday-halloween', 'holiday-halloween', true, 2,
                  CURRENT_TIMESTAMP, datetime('now', '-600 seconds')
                )
                """
            )
        )
    with session_factory() as db:
        release_queue_failures(
            db,
            {"B0FAIL0001": "name 'RuleEvaluation' is not defined"},
        )
        row = db.execute(
            text("SELECT picked, retry_count, last_error FROM enrich_queue WHERE asin='B0FAIL0001'")
        ).mappings().one()
        released = CategoryScheduler().release_stale_picks(db, older_than_seconds=1)
        after_stale = db.execute(
            text("SELECT picked, retry_count, last_error FROM enrich_queue WHERE asin='B0FAIL0001'")
        ).mappings().one()

    assert bool(row["picked"]) is True
    assert row["retry_count"] == 3
    assert str(row["last_error"]).startswith("dead_letter:")
    assert released == 0
    assert bool(after_stale["picked"]) is True
    assert str(after_stale["last_error"]).startswith("dead_letter:")


def test_queue_failures_keep_transient_keepa_errors_retryable():
    engine = create_engine("sqlite:///:memory:")
    session_factory = sessionmaker(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE enrich_queue (
                  asin TEXT PRIMARY KEY,
                  marketplace TEXT,
                  source_query TEXT,
                  category_id TEXT,
                  category_path TEXT,
                  picked BOOLEAN,
                  retry_count INTEGER,
                  last_error TEXT,
                  enqueued_at TEXT,
                  picked_at TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO enrich_queue (
                  asin, marketplace, source_query, category_id,
                  category_path, picked, retry_count, enqueued_at, picked_at
                )
                VALUES (
                  'B0RATE0001', 'US', 'keepa_category:1055398',
                  '1055398', '1055398', true, 2,
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
        )
    with session_factory() as db:
        release_queue_failures(db, {"B0RATE0001": "HTTP Error 429: Too Many Requests"})
        row = db.execute(
            text("SELECT picked, retry_count, last_error, picked_at FROM enrich_queue WHERE asin='B0RATE0001'")
        ).mappings().one()

    assert bool(row["picked"]) is False
    assert row["retry_count"] == 3
    assert str(row["last_error"]) == "HTTP Error 429: Too Many Requests"
    assert row["picked_at"] is None


def test_deepseek_batch_processor_has_no_scheduling_authority():
    provider = KeepaProvider(force_mock=True)
    repository = MockWarehouseRepository()
    engine = WarehouseEngine(
        provider=provider,
        rule_engine=RuleEngine(),
        repository=repository,
    )

    record = engine.ingest("portable door draft stopper", category_id="home-draft-proofing")[0]
    result = engine.process_discovered_asin(record)

    assert result.rule_evaluation.passed is True
    assert result.deepseek_screening is not None
    assert result.product.state is ProductState.AI1_PASSED
    assert result.product.features["deepseek_mode"] == "batch_processor_only"
    assert repository.ai_evaluations


def test_deepseek_batch_processor_returns_pass_fail_report():
    repository = MockWarehouseRepository()
    engine = WarehouseEngine(
        provider=KeepaProvider(force_mock=True),
        rule_engine=RuleEngine(),
        repository=repository,
        deepseek_skill=DeepSeekScreeningSkill(),
    )
    record = engine.ingest("portable door draft stopper")[0]
    result = engine.process_discovered_asin(record)

    batch = engine.deepseek_skill.evaluate_batch([result.product])

    assert batch.report_summary["mode"] == "batch_processor_only"
    assert batch.report_summary["scheduling_authority"] is False
    assert batch.report_summary["total_processed"] == 1
    assert batch.pass_products or batch.fail_products


def test_deepseek_skill_metadata_reads_version_from_skill_doc(tmp_path):
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text(
        "---\nname: product-selection\nversion: v1\n---\nDeepSeek\n量化过滤器\n",
        encoding="utf-8",
    )

    metadata = load_deepseek_skill_metadata(skill_path)
    assert metadata["installed"] is True
    assert metadata["version"] == "v1"
    assert metadata["label"] == "已安装 DeepSeek 初筛技能 v1"
