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
from r_system_v2.rw.core.models import IngestionRecord, NormalizedProduct, ProductState
from r_system_v2.rw.core.rule_engine import RuleEngine
from r_system_v2.rw.core.warehouse_engine import WarehouseEngine
from r_system_v2.rw.ai.deepseek_screening import DeepSeekScreeningSkill
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
