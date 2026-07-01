"""Warehouse core engine for R-W."""

from __future__ import annotations

import time

from r_system_v2.rw.core.models import IngestionRecord, PipelineResult, ProductState, RuleDecision
from r_system_v2.rw.core.rule_engine import RuleEngine
from r_system_v2.rw.ingestion.asin_ingestor import build_ingestion_records
from r_system_v2.rw.processor.feature_extractor import extract_product_features
from r_system_v2.rw.providers.keepa_provider import KeepaProvider
from r_system_v2.rw.storage.repository import MockWarehouseRepository


class WarehouseEngine:
    """Run ASIN ingestion, mock enrichment, feature extraction, and rules."""

    def __init__(
        self,
        provider: KeepaProvider | None = None,
        rule_engine: RuleEngine | None = None,
        repository: MockWarehouseRepository | None = None,
    ) -> None:
        self.provider = provider or KeepaProvider()
        self.rule_engine = rule_engine or RuleEngine()
        self.repository = repository or MockWarehouseRepository()

    def ingest(self, value: str | list[str], marketplace: str = "US") -> list[IngestionRecord]:
        records = build_ingestion_records(value, marketplace=marketplace)
        for record in records:
            self.repository.enqueue(record)
        return records

    def process_discovered_asin(self, record: IngestionRecord) -> PipelineResult:
        start = time.perf_counter()
        transitions = [record.state.value]

        keepa_data = self.provider.fetch_product(record.asin, source_query=record.source_query)
        self.repository.mark_enriched(record.asin)

        product = extract_product_features(record.source_query, keepa_data)
        transitions.append(ProductState.ENRICHED.value)

        rule_evaluation = self.rule_engine.evaluate(product)
        if rule_evaluation.decision is RuleDecision.RULE_PASSED:
            product.transition_to(ProductState.RULE_PASSED)
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
            transitions=transitions,
            latency_ms=round((time.perf_counter() - start) * 1000, 3),
        )

