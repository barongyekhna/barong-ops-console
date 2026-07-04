from __future__ import annotations

import asyncio

import pytest

from backend.app.services import api_key_orchestration
from backend.app.services.api_key_usage_tracker import api_key_usage_tracker
from r_system_v2.rw.core.keepa_buffer_queue import KeepaBufferQueue
from r_system_v2.rw.core.models import (
    DeepSeekScreening,
    IngestionRecord,
    KeepaProductData,
    NormalizedProduct,
    PipelineResult,
    ProductState,
    RuleDecision,
    RuleEvaluation,
)
from r_system_v2.rw.providers.keepa_provider import KeepaProvider
from r_system_v2.rw.storage.batch_writer import InMemoryBatchWriter
from r_system_v2.rw.workers.keepa_worker import KeepaWorker


pytestmark = pytest.mark.unit


def _pipeline_result(index: int) -> PipelineResult:
    asin = f"B0FIX{index:05d}"[-10:]
    ingestion = IngestionRecord(asin=asin, source_query=f"product {index}")
    keepa_data = KeepaProductData(
        asin=asin,
        price=34.99,
        bsr=8000 + index,
        reviews=200,
        seller_count=7,
        category="Home & Kitchen",
        title=f"Product {index}",
        brand="BatchBrand",
        landed_cost=12.25,
        brand_share=0.25,
        price_trend="stable",
        rating=4.4,
    )
    product = NormalizedProduct(
        asin=asin,
        source_query=ingestion.source_query,
        marketplace="US",
        title=keepa_data.title,
        brand=keepa_data.brand,
        category=keepa_data.category,
        price=keepa_data.price,
        bsr=keepa_data.bsr,
        reviews=keepa_data.reviews,
        seller_count=keepa_data.seller_count,
        landed_cost=keepa_data.landed_cost,
        est_net_margin=0.31,
        brand_share=keepa_data.brand_share,
        price_trend=keepa_data.price_trend,
        rating=keepa_data.rating,
        skill_score=78,
        state=ProductState.AI1_PASSED,
        features={"source": "test"},
    )
    rule_evaluation = RuleEvaluation(
        asin=asin,
        decision=RuleDecision.RULE_PASSED,
        reasons=[],
        checks={"price_band_filter": True},
    )
    screening = DeepSeekScreening(
        asin=asin,
        score=78,
        verdict="keep",
        competition_attackability=72,
        demand_quality=81,
        top_reason="unit test fixture",
        channel_guess="amazon",
        strict_json={
            "score": 78,
            "verdict": "keep",
            "competition_attackability": 72,
            "demand_quality": 81,
            "top_reason": "unit test fixture",
            "channel_guess": "amazon",
        },
        skill_loaded=True,
        quant_filter_enabled=True,
        rule_based_scoring_active=True,
        output_schema_strict_json=True,
    )
    return PipelineResult(
        asin=asin,
        ingestion=ingestion,
        keepa_data=keepa_data,
        product=product,
        rule_evaluation=rule_evaluation,
        deepseek_screening=screening,
        transitions=["discovered", "enriched", "rule_passed", "ai1_passed"],
        latency_ms=1.0,
    )


def test_api_key_resolution_tracks_usage_without_db_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    api_key_usage_tracker.clear_for_tests()
    binding = api_key_orchestration.ApiKeyModuleBindingRecord(
        binding_id="akb_keepa",
        org_id="org_keepa",
        module_id=api_key_orchestration.R_WAREHOUSE_MODULE_ID,
        key_id="key_keepa",
        key_alias=api_key_orchestration.KEEPA_KEY_ALIAS,
        status="active",
    )
    key = api_key_orchestration.ApiKeyRecord(
        key_id="key_keepa",
        org_id="org_keepa",
        name="Keepa",
        url="https://api.keepa.com",
        encrypted_key_value="encrypted",
        key_fingerprint="f" * 64,
        key_hash_prefix="f" * 12,
        status="active",
        metadata_json={},
    )

    class FakeDB:
        def scalar(self, statement):
            del statement
            return binding

        def add(self, record):
            raise AssertionError(f"runtime resolver must not add records: {record}")

        def flush(self):
            raise AssertionError("runtime resolver must not flush")

    monkeypatch.setattr(api_key_orchestration, "get_api_key_record", lambda db, key_id: key)
    monkeypatch.setattr(api_key_orchestration, "_decrypt_key_value", lambda envelope: "secret")
    monkeypatch.setattr(
        api_key_orchestration,
        "_key_type_payload",
        lambda record: {
            "key_type": api_key_orchestration.KEEPA_KEY_TYPE,
            "provider": "keepa",
            "auth_type": "api_key",
            "scope": [api_key_orchestration.R_WAREHOUSE_MODULE_ID],
            "validation_endpoint": "https://api.keepa.com/token?key={key}",
            "adapter": "KeepaAdapter",
        },
    )

    context = api_key_orchestration.resolve_module_api_key_for_injection(
        FakeDB(),
        org_id="org_keepa",
        module_id=api_key_orchestration.R_WAREHOUSE_MODULE_ID,
        key_alias=api_key_orchestration.KEEPA_KEY_ALIAS,
    )

    assert context.query_param_value == "secret"
    assert context.key_id == "key_keepa"
    assert api_key_usage_tracker.pending_count() == 1


def test_keepa_buffer_queue_flushes_one_batch_without_per_item_commits() -> None:
    writer = InMemoryBatchWriter()
    buffer = KeepaBufferQueue(writer=writer.write, batch_size=100, flush_interval_seconds=5)

    async def run() -> None:
        for index in range(100):
            await buffer.put(_pipeline_result(index))

    asyncio.run(run())

    stats = buffer.stats()
    assert stats.total_enqueued == 100
    assert stats.total_flushed == 100
    assert stats.flush_count == 1
    assert stats.active is True
    assert writer.transaction_count == 1
    assert writer.max_batch_size == 100
    assert writer.reports[-1].per_item_commits is False


def test_async_keepa_worker_queues_results_and_flushes_batch_writer() -> None:
    class FakeDeepSeekSkill:
        def evaluate(self, product: NormalizedProduct) -> DeepSeekScreening:
            return DeepSeekScreening(
                asin=product.asin,
                score=80,
                verdict="keep",
                competition_attackability=75,
                demand_quality=82,
                top_reason="fake skill",
                channel_guess="amazon",
                strict_json={
                    "score": 80,
                    "verdict": "keep",
                    "competition_attackability": 75,
                    "demand_quality": 82,
                    "top_reason": "fake skill",
                    "channel_guess": "amazon",
                },
                skill_loaded=True,
                quant_filter_enabled=True,
                rule_based_scoring_active=True,
                output_schema_strict_json=True,
            )

    writer = InMemoryBatchWriter()
    buffer = KeepaBufferQueue(writer=writer.write, batch_size=100, flush_interval_seconds=5)
    worker = KeepaWorker(
        provider=KeepaProvider(force_mock=True),
        buffer_queue=buffer,
        deepseek_skill=FakeDeepSeekSkill(),  # type: ignore[arg-type]
        enforce_wall_clock_rate=False,
    )
    records = [
        IngestionRecord(asin=f"B0ASY{i:05d}"[-10:], source_query="portable door draft stopper")
        for i in range(20)
    ]
    worker.enqueue(records)

    async def run() -> None:
        report = await worker.run_once()
        assert report.processed == 20
        assert report.failed == 0
        assert report.async_fetch is True
        assert report.per_request_db_update is False
        assert buffer.stats().pending == 20
        assert writer.transaction_count == 0
        await buffer.flush()

    asyncio.run(run())

    assert writer.transaction_count == 1
    assert len(writer.products) == 20
    assert writer.max_batch_size == 20


def test_holiday_keepa_worker_processes_sales_only_products_without_retry_error() -> None:
    class FakeDeepSeekSkill:
        pass

    writer = InMemoryBatchWriter()
    buffer = KeepaBufferQueue(writer=writer.write, batch_size=100, flush_interval_seconds=5)
    worker = KeepaWorker(
        provider=KeepaProvider(force_mock=True),
        buffer_queue=buffer,
        deepseek_skill=FakeDeepSeekSkill(),  # type: ignore[arg-type]
        enforce_wall_clock_rate=False,
    )
    worker.enqueue(
        [
            IngestionRecord(
                asin="B0HOLIDAY1",
                source_query="keepa_category:holiday-halloween",
                category_id="holiday-halloween",
            )
        ]
    )

    async def run() -> None:
        report = await worker.run_once()
        assert report.processed == 1
        assert report.failed == 0
        await buffer.flush()

    asyncio.run(run())

    product = writer.products["B0HOLIDAY1"]
    assert product["state"] == ProductState.AI1_PASSED.value
    assert product["features"]["hard_rule_exempt"] is True
    assert product["features"]["deepseek_mode"] == "skipped_holiday_sales_only"
