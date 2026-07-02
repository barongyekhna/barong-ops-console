"""Run the required R-W mock E2E pipeline test."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r_system_v2.rw.core.rule_engine import RuleEngine
from r_system_v2.rw.core.warehouse_engine import WarehouseEngine
from r_system_v2.rw.providers.keepa_provider import KeepaProvider
from r_system_v2.rw.scheduler.keepa_scheduler import KeepaScheduler
from r_system_v2.rw.storage.repository import MockWarehouseRepository


REPORT_PATH = REPO_ROOT / "R_W_MOCK_E2E_REPORT.json"
MOCK_STORAGE_PATH = Path("/tmp/rw_mock_storage/R_W_MOCK_STORAGE.json")
TEST_INPUT = "portable door draft stopper"


def run() -> dict[str, object]:
    start = time.perf_counter()

    repository = MockWarehouseRepository(persist_path=MOCK_STORAGE_PATH)
    provider = KeepaProvider(force_mock=True)
    engine = WarehouseEngine(
        provider=provider,
        rule_engine=RuleEngine(),
        repository=repository,
    )
    scheduler = KeepaScheduler(
        provider=provider,
        processor=engine.process_discovered_asin,
        rate_limit_per_min=20,
    )

    records = engine.ingest(TEST_INPUT)
    scheduler.enqueue(records)
    scheduler_report = scheduler.run_once()
    results = scheduler.results
    first_result = results[0] if results else None
    snapshot = repository.snapshot()

    pipeline_latency = round((time.perf_counter() - start) * 1000, 3)
    storage_write_ok = (
        bool(snapshot["products_rw"])
        and bool(snapshot["rule_results"])
        and bool(snapshot["ai_evaluations"])
        and repository.write_count >= 5
    )
    pipeline_integrity_ok = bool(
        first_result
        and first_result.transitions[:3] == ["discovered", "enriched", "rule_passed"]
        and first_result.transitions[-1] in {"ai1_passed", "ai1_rejected", "rejected"}
    )
    success = all(
        [
            bool(records),
            provider.mock_mode,
            bool(first_result),
            scheduler_report.success,
            storage_write_ok,
            pipeline_integrity_ok,
        ]
    )

    report: dict[str, object] = {
        "test_input": TEST_INPUT,
        "ingestion_status": "OK" if records else "FAILED",
        "ingested_asins": [record.asin for record in records],
        "mock_data_generated": bool(first_result and first_result.keepa_data.mock_generated),
        "rule_engine_result": first_result.rule_evaluation.to_dict() if first_result else None,
        "deepseek_result": first_result.deepseek_screening.to_dict() if first_result and first_result.deepseek_screening else None,
        "storage_write_status": "OK" if storage_write_ok else "FAILED",
        "scheduler": scheduler_report.to_dict(),
        "state_transitions": first_result.transitions if first_result else [],
        "pipeline_integrity": "OK" if pipeline_integrity_ok else "FAILED",
        "pipeline_latency": pipeline_latency,
        "pipeline_latency_ms": pipeline_latency,
        "success": success,
        "status": "success" if success else "failure",
        "mock_storage_path": str(MOCK_STORAGE_PATH),
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
