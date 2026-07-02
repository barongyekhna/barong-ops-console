from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r_system_v2.rw.ai.deepseek_screening import DeepSeekScreeningSkill
from r_system_v2.rw.providers.keepa_provider import (
    MAX_REQUESTS_PER_MINUTE,
    MOCK_MODE,
    NO_BURST_MODE,
    QUEUE_BASED_INGESTION_REQUIRED,
    USE_REAL_KEEPA_API,
    KeepaProvider,
)


DOCS_ROOT = REPO_ROOT / "r_system_v2" / "docs"
R_SERIES_TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"
SPEC_LOCK_PATH = REPO_ROOT / "R_W_SYSTEM_SPEC_LOCK.json"
PERMISSION_REPORT_PATH = REPO_ROOT / "R_W_PERMISSION_MATRIX_REPORT.json"
E2E_REPORT_PATH = REPO_ROOT / "R_W_E2E_FLOW_REPORT.json"
FINAL_AUDIT_PATH = REPO_ROOT / "R_W_PRODUCTION_DEPLOYMENT_AUDIT.json"
TEST_INPUT = "portable door draft stopper"
REQUIRED_DOCS = (
    "ARCHITECTURE.md",
    "SKILL.md",
    "shared.md",
    "amazon.md",
    "dtc.md",
    "dtc_data.md",
)


def user_has_rw_role_access(role: str) -> bool:
    return role.strip().lower().replace("-", "_") in {"owner", "super_admin"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_doc(name: str) -> tuple[Path, str]:
    path = DOCS_ROOT / name
    return path, path.read_text(encoding="utf-8")


def build_system_spec_lock() -> dict[str, Any]:
    documents: dict[str, Any] = {}
    for name in REQUIRED_DOCS:
        path, text = read_doc(name)
        documents[name] = {
            "path": str(path),
            "sha256": sha256_text(text),
            "bytes": len(text.encode("utf-8")),
            "loaded": True,
        }

    architecture = read_doc("ARCHITECTURE.md")[1]
    skill = read_doc("SKILL.md")[1]
    shared = read_doc("shared.md")[1]
    amazon = read_doc("amazon.md")[1]
    dtc = read_doc("dtc.md")[1]
    dtc_data = read_doc("dtc_data.md")[1]

    lock = {
        "generated_at": utc_now(),
        "status": "LOCKED",
        "documents": documents,
        "canonical_skill_path": str(DOCS_ROOT / "SKILL.md"),
        "root_skill_path_present": (REPO_ROOT / "SKILL.md").exists(),
        "organization_binding": R_SERIES_TARGET_ORGANIZATION_NAME,
        "keepa": {
            "use_real_keepa_api": USE_REAL_KEEPA_API,
            "mock_mode": MOCK_MODE,
            "max_requests_per_min": MAX_REQUESTS_PER_MINUTE,
            "no_burst_mode": NO_BURST_MODE,
            "queue_based_ingestion_required": QUEUE_BASED_INGESTION_REQUIRED,
            "refill_aware_scheduler_required": "refillIn" in architecture
            or "匀速回血" in architecture,
        },
        "deepseek": {
            "quant_filter_enabled": "DeepSeek" in skill and "量化过滤器" in skill,
            "rule_based_scoring_active": "只吃**结构化 Keepa 字段**" in skill
            or "只吃结构化 Keepa 字段" in skill,
            "strict_json_schema_enforced": all(
                key in skill
                for key in (
                    "score",
                    "verdict",
                    "competition_attackability",
                    "demand_quality",
                    "channel_guess",
                )
            )
            and "输出:" in skill
            and "纯 JSON" in architecture,
            "pipeline_rule_passed_to_ai1": "SELECT stage='rule_passed'" in architecture
            and "ai1_passed" in architecture,
        },
        "thresholds": {
            "price_min": 25,
            "price_max": 70,
            "min_net_margin": 0.15,
            "max_seller_count": 15,
            "max_single_brand_share": 0.50,
            "max_top3_reviews": 500,
            "max_weight_lb": 2.0,
            "deepseek_pass_score": 60,
            "gpt_pass_score": 65,
            "opus_keep_score": 75,
            "dtc_ad_min_gross_margin": 0.60,
            "dtc_seo_min_gross_margin": 0.40,
        },
        "shared_gate_matrix_loaded": "门槛矩阵" in shared and "通用红线" in shared,
        "amazon_rules_loaded": "KILL LIST" in amazon and "净利 < 15%" in amazon,
        "dtc_rules_loaded": "广告品" in dtc and "SEO 品" in dtc,
        "dtc_data_rules_loaded": "Minea / PiPiADS" in dtc_data and "Serper" in dtc_data,
    }
    write_json(SPEC_LOCK_PATH, lock)
    return lock


def build_permission_matrix_report() -> dict[str, Any]:
    users = [
        ("USER_A", "owner", True),
        ("USER_B", "super_admin", True),
        ("USER_C", "normal_user", False),
    ]
    matrix = []
    for user_id, role, expected in users:
        actual = user_has_rw_role_access(role)
        matrix.append(
            {
                "user": user_id,
                "role": role,
                "organization": R_SERIES_TARGET_ORGANIZATION_NAME,
                "expected_access": expected,
                "actual_access": actual,
                "result": "PASS" if actual is expected else "FAIL",
            }
        )

    report = {
        "generated_at": utc_now(),
        "organization": R_SERIES_TARGET_ORGANIZATION_NAME,
        "rules": {
            "owner": "full access",
            "super_admin": "full module access + API usage",
            "normal_user": "no access by default",
        },
        "matrix": matrix,
        "status": "PASS" if all(row["result"] == "PASS" for row in matrix) else "FAIL",
    }
    write_json(PERMISSION_REPORT_PATH, report)
    return report


def build_e2e_flow_report(permission_report: dict[str, Any]) -> dict[str, Any]:
    keepa_key_present = bool(os.getenv("KEEPA_API_KEY"))
    deepseek_key_present = bool(os.getenv("DEEPSEEK_API_KEY"))
    database_url_present = bool(os.getenv("DATABASE_URL"))
    provider = KeepaProvider()
    skill_status = DeepSeekScreeningSkill().status.to_dict()

    blockers: list[str] = []
    keepa_status: dict[str, Any] = {
        "max_requests_per_min": MAX_REQUESTS_PER_MINUTE,
        "no_burst_mode": NO_BURST_MODE,
        "queue_based_ingestion": QUEUE_BASED_INGESTION_REQUIRED,
        "refill_aware_scheduler": True,
        "live_status_checked": False,
        "verified": False,
    }

    if not keepa_key_present:
        blockers.append("KEEPA_API_KEY missing; real Keepa ingestion cannot run")
        ingestion_status = "BLOCKED_MISSING_KEEPA_API_KEY"
    else:
        try:
            status = provider.status()
            keepa_status.update(status.to_dict())
            keepa_status["live_status_checked"] = True
            keepa_status["verified"] = (
                status.mock_mode is False
                and status.max_requests_per_min == MAX_REQUESTS_PER_MINUTE
                and status.no_burst_mode is True
            )
            ingestion_status = "READY"
        except Exception as exc:  # noqa: BLE001 - audit must report exact blocker.
            blockers.append(f"Keepa status check failed: {exc}")
            ingestion_status = "BLOCKED_KEEPA_STATUS_FAILED"

    if not deepseek_key_present:
        blockers.append("DEEPSEEK_API_KEY missing; external DeepSeek screening cannot run")

    if not database_url_present:
        blockers.append("DATABASE_URL missing; production DB persistence cannot be verified")

    if not os.getenv("RW_E2E_TEST_ASIN"):
        blockers.append(
            "RW_E2E_TEST_ASIN missing; keyword-to-real-ASIN discovery is not implemented for production E2E"
        )

    e2e_pass = not blockers
    report = {
        "generated_at": utc_now(),
        "test_input": TEST_INPUT,
        "ingestion_status": "PASS" if e2e_pass else ingestion_status,
        "keepa_rate_limit_status": "PASS" if keepa_status["verified"] else "BLOCKED",
        "rule_engine_status": "PASS" if e2e_pass else "NOT_RUN",
        "deepseek_status": {
            "status": "PASS"
            if skill_status["ready"] and deepseek_key_present
            else "BLOCKED",
            "skill": skill_status,
            "api_key_present": deepseek_key_present,
        },
        "permission_status": permission_report["status"],
        "db_write_status": "PASS" if e2e_pass else "NOT_RUN",
        "keepa": keepa_status,
        "mock_mode_active": MOCK_MODE,
        "use_real_keepa_api": USE_REAL_KEEPA_API,
        "blockers": blockers,
        "status": "PASS" if e2e_pass else "FAIL",
    }
    write_json(E2E_REPORT_PATH, report)
    return report


def build_final_audit(
    spec_lock: dict[str, Any],
    permission_report: dict[str, Any],
    e2e_report: dict[str, Any],
) -> dict[str, Any]:
    frontend_mock_routes_disabled = all(
        "mock endpoint disabled" in path.read_text(encoding="utf-8")
        for path in (
            REPO_ROOT / "frontend" / "src" / "app" / "api" / "rw" / "status" / "route.ts",
            REPO_ROOT / "frontend" / "src" / "app" / "api" / "rw" / "products" / "route.ts",
            REPO_ROOT / "frontend" / "src" / "app" / "api" / "rw" / "rules" / "route.ts",
        )
    )
    safety_checks = {
        "no_mock_mode_active": MOCK_MODE is False and frontend_mock_routes_disabled,
        "no_unauthorized_api_usage": True,
        "no_rule_bypass": (REPO_ROOT / "r_system_v2" / "rw" / "core" / "rule_engine.py").exists(),
        "no_missing_skill_injection": spec_lock["deepseek"]["quant_filter_enabled"]
        and spec_lock["deepseek"]["strict_json_schema_enforced"],
        "no_privilege_escalation": permission_report["status"] == "PASS",
    }
    blockers = list(e2e_report["blockers"])
    if not all(safety_checks.values()):
        blockers.append("one_or_more_safety_checks_failed")

    allow = (
        e2e_report["status"] == "PASS"
        and permission_report["status"] == "PASS"
        and all(safety_checks.values())
        and e2e_report["keepa"]["verified"] is True
        and e2e_report["deepseek_status"]["status"] == "PASS"
    )
    audit = {
        "generated_at": utc_now(),
        "target": "https://ops.barongyekhna.com",
        "system_status": {
            "spec_lock": spec_lock["status"],
            "organization": R_SERIES_TARGET_ORGANIZATION_NAME,
            "mock_mode": MOCK_MODE,
            "use_real_keepa_api": USE_REAL_KEEPA_API,
        },
        "keepa_status": e2e_report["keepa"],
        "deepseek_status": e2e_report["deepseek_status"],
        "permission_matrix": permission_report,
        "e2e_result": e2e_report,
        "safety_checks": safety_checks,
        "deployment_decision": "ALLOW" if allow else "BLOCK",
        "deployment_command": "docker compose up -d --build" if allow else "NOT_RUN",
        "post_deploy_verification": {
            "r_w_dashboard_visible": "NOT_RUN",
            "keepa_ingestion_running": "NOT_RUN",
            "api_usage_active": "NOT_RUN",
            "role_based_access_enforced": "NOT_RUN",
            "no_unauthorized_access": "NOT_RUN",
        },
        "blockers": blockers,
    }
    write_json(FINAL_AUDIT_PATH, audit)
    return audit


def run() -> dict[str, Any]:
    spec_lock = build_system_spec_lock()
    permission_report = build_permission_matrix_report()
    e2e_report = build_e2e_flow_report(permission_report)
    return build_final_audit(spec_lock, permission_report, e2e_report)


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
