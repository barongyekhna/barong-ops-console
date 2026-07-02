from __future__ import annotations

from r_system_v2.rw.category.category_tree import (
    generate_category_tree_from_amazon_doc,
    select_category,
    selected_category_ids,
)
from r_system_v2.rw.core.models import IngestionRecord, ProductState
from r_system_v2.rw.core.rule_engine import RuleEngine
from r_system_v2.rw.core.warehouse_engine import WarehouseEngine
from r_system_v2.rw.ai.deepseek_screening import DeepSeekScreeningSkill
from r_system_v2.rw.providers.keepa_provider import KeepaProvider
from r_system_v2.rw.scheduler.category_rate_limiter import CategoryRateLimiter
from r_system_v2.rw.scheduler.keepa_scheduler import KeepaScheduler
from r_system_v2.rw.skill_metadata import load_deepseek_skill_metadata
from r_system_v2.rw.storage.repository import MockWarehouseRepository


def test_category_tree_parent_cascades_but_child_selection_is_local(tmp_path):
    doc_path = tmp_path / "amazon.md"
    tree_path = tmp_path / "category_tree.json"
    doc_path.write_text("避开: 锂电 / restricted / IP / 易碎", encoding="utf-8")

    generate_category_tree_from_amazon_doc(doc_path=doc_path, output_path=tree_path)
    parent_off = select_category("home-kitchen", False, path=tree_path)
    assert "home-kitchen" not in selected_category_ids(parent_off)
    assert "home-draft-proofing" not in selected_category_ids(parent_off)

    parent_on = select_category("home-kitchen", True, path=tree_path)
    assert "home-kitchen" in selected_category_ids(parent_on)
    assert "home-draft-proofing" in selected_category_ids(parent_on)

    child_off = select_category("office-organization", False, path=tree_path)
    assert "office-products" in selected_category_ids(child_off)
    assert "office-organization" not in selected_category_ids(child_off)


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
    assert metadata["label"] == "已安装 DeepSeek 初筛 Skill v1"
