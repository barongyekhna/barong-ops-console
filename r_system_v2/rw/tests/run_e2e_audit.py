"""Run the required R-W full E2E audit."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r_system_v2.rw.core.warehouse_engine import WarehouseEngine
from r_system_v2.rw.category.category_tree import load_category_tree, selected_category_ids
from r_system_v2.rw.core.models import KeepaProductData
from r_system_v2.rw.core.rule_engine import RuleEngine
from r_system_v2.rw.processor.feature_extractor import extract_product_features
from r_system_v2.rw.providers.keepa_provider import KeepaProvider
from r_system_v2.rw.scheduler.keepa_scheduler import KeepaScheduler
from r_system_v2.rw.storage.repository import MockWarehouseRepository


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
    engine = WarehouseEngine(
        provider=provider,
        repository=repository,
    )
    records = engine.ingest("portable door draft stopper")
    scheduler = KeepaScheduler(provider=provider, processor=engine.process_discovered_asin)
    scheduler.enqueue(records)
    scheduler_report = scheduler.run_once()

    result = scheduler.results[0] if scheduler.results else None
    expected_terminal_states = {"ai1_passed", "ai1_rejected", "rejected"}
    transition_valid = bool(
        result
        and result.transitions[0] == "discovered"
        and result.transitions[1] == "enriched"
        and result.transitions[-1] in expected_terminal_states
    )
    storage_valid = bool(
        repository.products
        and repository.rule_results
        and repository.ai_evaluations
        and not repository.enrich_queue
    )
    runtime_ok = bool(result and result.success and scheduler_report.success and transition_valid and storage_valid)

    return runtime_ok, {
        "runtime_error": None,
        "scheduler": scheduler_report.to_dict(),
        "transition_valid": transition_valid,
        "storage_valid": storage_valid,
        "result": result.to_dict() if result else None,
    }


def _validate_regressions() -> tuple[bool, dict[str, object]]:
    category_tree = load_category_tree()
    selected_categories = selected_category_ids(category_tree)
    root = category_tree.get("root", {})
    category_ok = (
        isinstance(root, dict)
        and root.get("id") != "amazon-fba"
        and len(selected_categories) >= 8
        and all("fba" not in category.lower() for category in selected_categories)
    )

    lithium_keepa = KeepaProductData(
        asin="B0TEST0001",
        price=39.99,
        bsr=12_000,
        reviews=120,
        seller_count=6,
        category="Tools & Home Improvement",
        title="Rechargeable Lithium Work Light",
        brand="TestBrand",
        landed_cost=None,
        brand_share=0.2,
        price_trend="stable",
        fulfillment_method="FBA",
        lithium_battery_warning=True,
        margin_source="missing_landed_cost",
        margin_confidence="unknown",
        mock_generated=False,
    )
    lithium_product = extract_product_features("test", lithium_keepa)
    lithium_eval = RuleEngine().evaluate(lithium_product)
    margin_not_faked = lithium_product.est_net_margin is None
    lithium_not_hard_rejected = "redline_category" not in lithium_eval.reasons
    fulfillment_marked = lithium_product.fulfillment_method == "FBA"

    settings_source = (RW_ROOT / "storage" / "runtime_settings.py").read_text(encoding="utf-8")
    schedule_closed = all(
        marker in settings_source
        for marker in (
            "deepseek_schedule_enabled",
            "deepseek_window_start",
            "deepseek_window_end",
            "deepseek_timezone",
        )
    )

    ok = all(
        [
            category_ok,
            margin_not_faked,
            lithium_not_hard_rejected,
            fulfillment_marked,
            schedule_closed,
        ]
    )
    return ok, {
        "category_ok": category_ok,
        "selected_category_count": len(selected_categories),
        "root_id": root.get("id") if isinstance(root, dict) else None,
        "margin_not_faked": margin_not_faked,
        "lithium_not_hard_rejected": lithium_not_hard_rejected,
        "fulfillment_marked": fulfillment_marked,
        "deepseek_schedule_window_supported": schedule_closed,
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
    try:
        regressions_ok, regression_details = _validate_regressions()
    except Exception as exc:
        regressions_ok = False
        regression_details = {"regression_error": str(exc)}

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
            regressions_ok,
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
        "regressions_ok": regressions_ok,
        "regression_details": regression_details,
        "runtime_details": runtime_details,
        "success": success,
        "status": "success" if success else "failure",
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
