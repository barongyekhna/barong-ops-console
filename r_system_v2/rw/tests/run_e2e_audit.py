"""Run the required R-W full E2E audit."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from r_system_v2.rw.core.warehouse_engine import WarehouseEngine
from r_system_v2.rw.providers.keepa_provider import KeepaProvider
from r_system_v2.rw.scheduler.keepa_scheduler import KeepaScheduler
from r_system_v2.rw.storage.repository import MockWarehouseRepository


REPO_ROOT = Path(__file__).resolve().parents[3]
R_SYSTEM_ROOT = REPO_ROOT / "r_system_v2"
RW_ROOT = R_SYSTEM_ROOT / "rw"
REPORT_PATH = REPO_ROOT / "R_W_E2E_AUDIT_REPORT.json"

REQUIRED_PATHS = [
    RW_ROOT / "ingestion",
    RW_ROOT / "scheduler",
    RW_ROOT / "processor",
    RW_ROOT / "rules",
    RW_ROOT / "storage",
    RW_ROOT / "core" / "warehouse_engine.py",
    RW_ROOT / "core" / "rule_engine.py",
    RW_ROOT / "providers" / "keepa_provider.py",
    RW_ROOT / "scheduler" / "keepa_scheduler.py",
    R_SYSTEM_ROOT / "db" / "schema_rw.sql",
]

REQUIRED_IMPORTS = [
    "r_system_v2.rw.providers.keepa_provider",
    "r_system_v2.rw.core.warehouse_engine",
    "r_system_v2.rw.core.rule_engine",
    "r_system_v2.rw.scheduler.keepa_scheduler",
    "r_system_v2.rw.storage.repository",
    "r_system_v2.rw.ingestion.asin_ingestor",
    "r_system_v2.rw.processor.feature_extractor",
]


def _validate_imports() -> tuple[bool, list[str]]:
    errors: list[str] = []
    for module_name in REQUIRED_IMPORTS:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
    return not errors, errors


def _validate_runtime_flow() -> tuple[bool, dict[str, object]]:
    repository = MockWarehouseRepository()
    provider = KeepaProvider(force_mock=True)
    engine = WarehouseEngine(provider=provider, repository=repository)
    records = engine.ingest("portable door draft stopper")
    scheduler = KeepaScheduler(provider=provider, processor=engine.process_discovered_asin)
    scheduler.enqueue(records)
    scheduler_report = scheduler.run_once()

    result = scheduler.results[0] if scheduler.results else None
    expected_terminal_states = {"rule_passed", "rejected"}
    transition_valid = bool(
        result
        and result.transitions[0] == "discovered"
        and result.transitions[1] == "enriched"
        and result.transitions[-1] in expected_terminal_states
    )
    storage_valid = bool(repository.products and repository.rule_results and not repository.enrich_queue)
    runtime_ok = bool(result and result.success and scheduler_report.success and transition_valid and storage_valid)

    return runtime_ok, {
        "runtime_error": None,
        "scheduler": scheduler_report.to_dict(),
        "transition_valid": transition_valid,
        "storage_valid": storage_valid,
        "result": result.to_dict() if result else None,
    }


def run() -> dict[str, object]:
    missing_paths = [str(path.relative_to(REPO_ROOT)) for path in REQUIRED_PATHS if not path.exists()]
    imports_ok, import_errors = _validate_imports()

    runtime_details: dict[str, object]
    try:
        runtime_ok, runtime_details = _validate_runtime_flow()
    except Exception as exc:
        runtime_ok = False
        runtime_details = {"runtime_error": str(exc)}

    no_missing_module = not missing_paths
    no_broken_import = imports_ok
    no_runtime_error = runtime_ok and not runtime_details.get("runtime_error")
    pipeline_flow_integrity = bool(runtime_details.get("scheduler", {}).get("processed") == 1 and runtime_details.get("storage_valid"))
    data_state_transitions_valid = bool(runtime_details.get("transition_valid"))
    success = all(
        [
            no_missing_module,
            no_broken_import,
            no_runtime_error,
            pipeline_flow_integrity,
            data_state_transitions_valid,
        ]
    )

    report: dict[str, object] = {
        "no_missing_module": no_missing_module,
        "missing_paths": missing_paths,
        "no_broken_import": no_broken_import,
        "import_errors": import_errors,
        "no_runtime_error": no_runtime_error,
        "pipeline_flow_integrity": pipeline_flow_integrity,
        "data_state_transitions_valid": data_state_transitions_valid,
        "runtime_details": runtime_details,
        "success": success,
        "status": "success" if success else "failure",
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
