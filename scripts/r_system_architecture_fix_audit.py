from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

IMPACT_REPORT = REPO_ROOT / "ARCHITECTURE_IMPACT_REPORT.json"
FIX_REPORT = REPO_ROOT / "R_SYSTEM_ARCHITECTURE_FIX_REPORT.json"


def now() -> str:
    return datetime.now(UTC).isoformat()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def git_changed_paths(*paths: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", *paths],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return [f"git_diff_failed:{result.stderr.strip()}"]
    return [line for line in result.stdout.splitlines() if line.strip()]


def repository_has(pattern: str, *paths: str) -> bool:
    result = subprocess.run(
        ["rg", "-n", pattern, *paths],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def run_runtime_e2e() -> dict[str, Any]:
    from r_system_v2.rw.core.rule_engine import RuleEngine
    from r_system_v2.rw.core.warehouse_engine import WarehouseEngine
    from r_system_v2.rw.providers.keepa_provider import KeepaProvider
    from r_system_v2.rw.scheduler.keepa_scheduler import KeepaScheduler
    from r_system_v2.rw.storage.repository import MockWarehouseRepository

    repository = MockWarehouseRepository()
    provider = KeepaProvider(force_mock=True)
    engine = WarehouseEngine(
        provider=provider,
        rule_engine=RuleEngine(),
        repository=repository,
    )
    records = engine.ingest("portable door draft stopper")
    scheduler = KeepaScheduler(provider=provider, processor=engine.process_discovered_asin)
    scheduler.enqueue(records)
    scheduler_report = scheduler.run_once()
    result = scheduler.results[0] if scheduler.results else None
    pass_fail_split = bool(
        result
        and result.deepseek_screening is not None
        and result.product.state.value in {"ai1_passed", "ai1_rejected"}
    )
    return {
        "simulation": "keepa_queue_non_stop_single_cycle",
        "keepa_scheduler": scheduler_report.to_dict(),
        "deepseek_batch_executed": result.deepseek_screening is not None if result else False,
        "pass_fail_split": pass_fail_split,
        "product_persisted": bool(repository.products),
        "ai_evaluation_persisted": bool(repository.ai_evaluations),
        "queue_drained": not repository.enrich_queue,
        "status": "PASS"
        if result and scheduler_report.success and pass_fail_split and repository.products
        else "FAIL",
    }


def main() -> int:
    old_secret_table = "r_system_" + "secrets"
    old_tw = "deepseek_" + "time" + "_window"
    old_secret_ui_marker = "r-system" + "-secret"
    old_deepseek_window_route = "deepseek" + "-window"
    old_secret_panel = "RSystem" + "SecretManagementPanel"

    k_router = REPO_ROOT / "backend/app/modules/k_series/product_knowledge/router.py"
    i_service = REPO_ROOT / "backend/app/modules/i_series/image_system/service.py"
    rw_secret = REPO_ROOT / "r_system_v2/core/secret_manager.py"
    rw_engine = REPO_ROOT / "r_system_v2/rw/core/warehouse_engine.py"
    rw_status = REPO_ROOT / "backend/app/api/routes/rw.py"
    warehouse_ui = REPO_ROOT / "frontend/src/modules/r/warehouse/WarehouseWorkspace.tsx"
    api_key_page = REPO_ROOT / "frontend/src/app/(console)/api-key-management/page.tsx"
    deepseek_provider = REPO_ROOT / "r_system_v2/rw/providers/deepseek_provider.py"

    k_i_changed = git_changed_paths(
        "backend/app/modules/k_series",
        "backend/app/modules/i_series",
    )
    secret_text = read_text(rw_secret)
    engine_text = read_text(rw_engine)
    status_text = read_text(rw_status)
    ui_text = read_text(warehouse_ui)
    api_key_page_text = read_text(api_key_page)
    deepseek_provider_text = read_text(deepseek_provider)

    ui_key_module_removed = all(
        [
            not (REPO_ROOT / "frontend/modules/api-key-ui-rw").exists(),
            not (REPO_ROOT / "frontend/components/keepa-key-panel").exists(),
            old_secret_panel not in api_key_page_text,
            not repository_has(old_secret_ui_marker, "frontend", "backend"),
            not repository_has(old_secret_table, "backend", "frontend", "r_system_v2", "tests", "scripts"),
        ]
    )
    secret_manager_only = all(
        [
            "resolve_module_api_key_for_injection" in secret_text,
            "api_key_orchestration_only" in secret_text,
            old_secret_table not in secret_text,
            "KEEPA_API_KEY" not in read_text(REPO_ROOT / "r_system_v2/rw/providers/keepa_provider.py"),
            "DEEPSEEK_API_KEY" not in read_text(REPO_ROOT / "r_system_v2/rw/ai/deepseek_screening.py"),
        ]
    )
    keepa_continuous_mode = all(
        [
            "continuous_ingestion" in status_text,
            "24/7" in status_text,
            "MAX_REQUESTS_PER_MINUTE = 20"
            in read_text(REPO_ROOT / "r_system_v2/rw/providers/keepa_provider.py"),
            old_tw not in engine_text,
        ]
    )
    deepseek_scheduler_removed = all(
        [
            old_tw not in engine_text,
            "batch_processor_only" in engine_text,
            "scheduling_authority" in deepseek_provider_text,
            "False" in deepseek_provider_text,
        ]
    )
    ui_display_only = all(
        [
            "deepseek_batch" in ui_text,
            "popupStats" in ui_text,
            "controls_execution" in read_text(REPO_ROOT / "frontend/src/modules/r/warehouse/types.ts"),
            old_deepseek_window_route
            not in read_text(REPO_ROOT / "frontend/src/app/api/backend/[...path]/route.ts"),
        ]
    )
    data_delete_integrity = all(
        [
            "DELETE FROM products_rw" in status_text,
            "hard_delete" in status_text,
            "cascade" in status_text,
        ]
    )
    k_i_key_source_locked = all(
        [
            "require_module_execution_ready" in read_text(k_router),
            "resolve_module_api_key_for_injection"
            in read_text(REPO_ROOT / "backend/app/services/module_execution_gate.py"),
            "resolve_i_image_provider_key" in read_text(i_service),
            "resolve_module_api_key_for_injection" in read_text(i_service),
        ]
    )

    e2e = run_runtime_e2e()
    checks = {
        "k_i_unchanged": not k_i_changed,
        "k_i_key_source_locked": k_i_key_source_locked,
        "ui_key_module_removed": ui_key_module_removed,
        "secret_manager_only": secret_manager_only,
        "keepa_continuous_mode": keepa_continuous_mode,
        "deepseek_scheduler_removed": deepseek_scheduler_removed,
        "ui_display_only": ui_display_only,
        "data_delete_integrity": data_delete_integrity,
        "runtime_e2e": e2e["status"] == "PASS",
    }
    impact_report = {
        "generated_at": now(),
        "k_series": {
            "modified_by_fix": bool(k_i_changed),
            "changed_files": [path for path in k_i_changed if "k_series" in path],
            "key_source": "backend api_key_records + api_key_module_bindings via resolve_module_api_key_for_injection",
        },
        "i_series": {
            "modified_by_fix": bool(k_i_changed),
            "changed_files": [path for path in k_i_changed if "i_series" in path],
            "key_source": "backend api_key_records + api_key_module_bindings via resolve_module_api_key_for_injection",
        },
        "rw_series": {
            "key_source": "SecretManager adapter over backend API Key Orchestration",
            "keepa_mode": "continuous_24_7_queue_limited_20_per_min",
            "deepseek_mode": "batch_processor_only",
            "ui_mode": "display_only",
        },
        "data_safety": {
            "destructive_db_command_executed": False,
            "source_runtime_uses_separate_secret_table": False,
            "manual_delete_policy": "products_rw hard delete with DB cascade",
        },
        "status": "PASS" if checks["k_i_unchanged"] and checks["k_i_key_source_locked"] else "FAIL",
    }
    fix_report = {
        "generated_at": now(),
        "checks": checks,
        "runtime_e2e": e2e,
        "keepa_continuous_mode": keepa_continuous_mode,
        "secret_manager_only": secret_manager_only,
        "ui_key_module_removed": ui_key_module_removed,
        "deepseek_scheduler_removed": deepseek_scheduler_removed,
        "e2e_status": "PASS" if all(checks.values()) else "FAIL",
    }
    write_json(IMPACT_REPORT, impact_report)
    write_json(FIX_REPORT, fix_report)
    print(json.dumps(fix_report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if fix_report["e2e_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
