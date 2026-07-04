"""Storage adapters for Warehouse execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from r_system_v2.rw.ai.model_config import rw_deepseek_model
from r_system_v2.rw.core.models import (
    DeepSeekScreening,
    IngestionRecord,
    NormalizedProduct,
    RuleEvaluation,
)


class MockWarehouseRepository:
    """In-memory repository with optional JSON persistence for E2E tests."""

    def __init__(self, persist_path: Path | None = None) -> None:
        self.persist_path = persist_path
        self.products: dict[str, dict[str, Any]] = {}
        self.enrich_queue: dict[str, dict[str, Any]] = {}
        self.rule_results: list[dict[str, Any]] = []
        self.ai_evaluations: list[dict[str, Any]] = []
        self.write_count = 0

    def enqueue(self, record: IngestionRecord) -> None:
        self.enrich_queue[record.asin] = record.to_dict()
        self.write_count += 1
        self.flush()

    def mark_enriched(self, asin: str) -> None:
        if asin in self.enrich_queue:
            self.enrich_queue[asin]["picked"] = True
            self.write_count += 1
            self.flush()

    def upsert_product(self, product: NormalizedProduct) -> None:
        self.products[product.asin] = product.to_dict()
        self.write_count += 1
        self.flush()

    def save_rule_result(self, result: RuleEvaluation) -> None:
        self.rule_results.append(result.to_dict())
        self.write_count += 1
        self.flush()

    def save_ai_evaluation(self, result: DeepSeekScreening) -> None:
        self.ai_evaluations.append(
            {
                "asin": result.asin,
                "layer": "deepseek",
                "model": rw_deepseek_model(),
                "score": result.score,
                "verdict": result.verdict,
                "payload": result.strict_json,
                "created_at": result.evaluated_at,
            }
        )
        self.write_count += 1
        self.flush()

    def delete_queue_item(self, asin: str) -> None:
        self.enrich_queue.pop(asin, None)
        self.write_count += 1
        self.flush()

    def snapshot(self) -> dict[str, Any]:
        return {
            "products_rw": self.products,
            "enrich_queue": self.enrich_queue,
            "rule_results": self.rule_results,
            "ai_evaluations": self.ai_evaluations,
            "write_count": self.write_count,
        }

    def flush(self) -> None:
        if not self.persist_path:
            return
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self.persist_path.write_text(json.dumps(self.snapshot(), indent=2, sort_keys=True), encoding="utf-8")
