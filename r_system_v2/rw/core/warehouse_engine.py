"""Warehouse core engine for R-W."""

from __future__ import annotations

import time

from r_system_v2.rw.ai.deepseek_screening import DeepSeekScreeningSkill
from r_system_v2.rw.core.models import (
    DeepSeekScreening,
    IngestionRecord,
    PipelineResult,
    ProductState,
    RuleDecision,
)
from r_system_v2.rw.core.rule_engine import RuleEngine
from r_system_v2.rw.ingestion.asin_ingestor import build_ingestion_records
from r_system_v2.rw.processor.feature_extractor import extract_product_features
from r_system_v2.rw.providers.keepa_provider import KeepaProvider
from r_system_v2.rw.storage.repository import MockWarehouseRepository


class WarehouseEngine:
    """Run ASIN ingestion, enrichment, feature extraction, rules, and AI-1."""

    def __init__(
        self,
        provider: KeepaProvider | None = None,
        rule_engine: RuleEngine | None = None,
        repository: MockWarehouseRepository | None = None,
        deepseek_skill: DeepSeekScreeningSkill | None = None,
        org_id: str | None = None,
    ) -> None:
        self.provider = provider or KeepaProvider()
        self.rule_engine = rule_engine or RuleEngine()
        self.repository = repository or MockWarehouseRepository()
        self.deepseek_skill = deepseek_skill or DeepSeekScreeningSkill(org_id=org_id)

    def ingest(
        self,
        value: str | list[str],
        marketplace: str = "US",
        category_id: str | None = None,
    ) -> list[IngestionRecord]:
        records = build_ingestion_records(
            value,
            marketplace=marketplace,
            category_id=category_id,
        )
        for record in records:
            self.repository.enqueue(record)
        return records

    def process_discovered_asin(self, record: IngestionRecord) -> PipelineResult:
        start = time.perf_counter()
        transitions = [record.state.value]

        keepa_data = self.provider.fetch_product(record.asin, source_query=record.source_query)
        self.repository.mark_enriched(record.asin)

        product = extract_product_features(record.source_query, keepa_data)
        if record.category_id:
            product.category_id = record.category_id
            product.category_path = [record.category_id, product.category]
        transitions.append(ProductState.ENRICHED.value)
        deepseek_screening: DeepSeekScreening | None = None

        rule_evaluation = self.rule_engine.evaluate(product)
        if rule_evaluation.decision is RuleDecision.RULE_PASSED:
            product.transition_to(ProductState.RULE_PASSED)
            transitions.append(product.state.value)
            product.features["deepseek_mode"] = "batch_processor_only"
            deepseek_screening = self.deepseek_skill.evaluate(product)
            product.skill_score = deepseek_screening.score
            product.features["deepseek_score"] = deepseek_screening.score
            product.features["deepseek_verdict"] = deepseek_screening.verdict
            product.features["deepseek_reason"] = deepseek_screening.top_reason
            product.features["score_action"] = "pending_review"
            product.features["score_reason"] = deepseek_screening.top_reason
            product.features["ra_review_required"] = True
            self.repository.save_ai_evaluation(deepseek_screening)
            product.transition_to(ProductState.AI1_PASSED)
        else:
            product.rule_reject_reason = ",".join(rule_evaluation.reasons)
            product.transition_to(ProductState.REJECTED)

        transitions.append(product.state.value)
        self.repository.upsert_product(product)
        self.repository.save_rule_result(rule_evaluation)
        self.repository.delete_queue_item(record.asin)

        return PipelineResult(
            asin=record.asin,
            ingestion=record,
            keepa_data=keepa_data,
            product=product,
            rule_evaluation=rule_evaluation,
            deepseek_screening=deepseek_screening,
            transitions=transitions,
            latency_ms=round((time.perf_counter() - start) * 1000, 3),
        )
