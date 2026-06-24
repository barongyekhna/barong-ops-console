from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT_ID = f"recovery_blocked_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"


def now() -> str:
    return datetime.now(UTC).isoformat()


def write(name: str, payload: dict) -> None:
    payload.setdefault("audit_id", AUDIT_ID)
    payload.setdefault("generated_at", now())
    (ROOT / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


permission_report = {
    "status": "passed",
    "rbac_core_modified": False,
    "backend_route_enforcement": "POST /api/app/org/create now depends on require_owner",
    "service_layer_defense": "create_organization rejects non-owner roles before owner_user_id equality check",
    "real_runtime_evidence": {
        "verification_container": "barong-recovery-verify",
        "owner_create_org_status": 201,
        "created_roles": {
            "super_admin": 201,
            "admin": 422,
            "operator": 201,
            "viewer": 201,
        },
        "non_owner_create_org_attempts": {
            "super_admin": 403,
            "operator": 403,
            "viewer": 403,
        },
    },
    "remaining_role_gap": "admin cannot be created by current user-management policy",
}

execution_report = {
    "status": "blocked",
    "module_id": "integration.n8n_webhook_test_bridge",
    "mock_fallback_allowed": False,
    "real_route_added": "POST /api/control-plane/n8n-webhook-test/run",
    "real_runtime_evidence": {
        "api_key_create_status": 201,
        "api_key_binding_status": 201,
        "missing_key_fallback_status": 403,
        "configured_key_webhook_status": 503,
        "configured_key_error": "N8N_TEST_WEBHOOK_URL is empty",
    },
    "chain": [
        "module",
        "api_key_binding",
        "execution_gate",
        "backend_http_dispatch",
        "operation_log",
    ],
}

performance_report = {
    "status": "failed",
    "implemented_fixes": [
        "module-control center read path synthesizes default state without DB writes",
        "short TTL read caches added for organizations, permissions, and modules",
        "cached GET routes allow parallel idempotent reads while non-idempotent duplicate protection remains",
    ],
    "real_runtime_evidence": {
        "health_after_restart_ms": 4.756,
        "parallel_login_10_users": {
            "attempted": 10,
            "observed_http_200_in_logs": 10,
        },
        "read_50_rps": {
            "attempted": 50,
            "completed": 0,
            "result": "stage_timeout",
            "notes": "The verification run reached the 50 concurrent read phase and stopped progressing before backend access logs for those reads appeared.",
        },
        "resource_snapshot_after_timeout": {
            "verification_backend_cpu_percent": 26.49,
            "postgres_cpu_percent": 163.48,
            "postgres_pids": 66,
        },
    },
    "target": {"read_api_p95_ms": 500, "module_control_ms": 2000},
}

field_report = {
    "status": "blocked",
    "implemented_fixes": {
        "Users": ["organization", "title compatibility fields added"],
        "Modules": ["status", "error compatibility fields added"],
        "Approvals": ["reason", "timestamp fields added to list items"],
    },
    "real_runtime_evidence": {
        "organizations_list_status": 200,
        "users_list_status": 200,
        "permissions_registry_status": 200,
        "module_control_center_status": 200,
        "approval_list_status": 200,
        "approval_create_status": 422,
    },
    "blocking_issue": "Approval create still returned 422 in the real verification run; field validation is not final-pass verified.",
}

webhook_failure_report = {
    "status": "failed",
    "n8n_test_webhook_url_configured": False,
    "webhook_run_status": 503,
    "root_cause": "N8N_TEST_WEBHOOK_URL is empty in .env.production and in the production backend container.",
    "mock_fallback_used": False,
}

concurrency_report = {
    "status": "failed",
    "parallel_login": {
        "attempted": 10,
        "observed_http_200_in_logs": 10,
    },
    "read_50_rps": {
        "attempted": 50,
        "result": "stage_timeout",
        "failure_rate": 1.0,
    },
    "module_toggle_concurrency": {
        "attempted": 8,
        "result": "not_reached_after_read_stage_timeout",
    },
    "api_key_binding_concurrency": {
        "attempted": 3,
        "result": "not_reached_after_read_stage_timeout",
    },
}

readiness_report = {
    "system_can_go_live": "NO",
    "blocking_issues": [
        "n8n_test_webhook_url_missing",
        "n8n_webhook_e2e_failed",
        "read_50_rps_stage_timeout",
        "approval_create_422",
        "admin_role_user_creation_unsupported",
        "production_container_not_updated_with_current_code",
    ],
    "performance_summary": performance_report,
    "security_summary": permission_report,
    "webhook_validation_result": {
        "passed": False,
        "status_code": 503,
        "n8n_test_webhook_url_configured": False,
    },
    "deployment_summary": {
        "restart_allowed": False,
        "restart_executed": False,
        "reason": "Blocking issues remain; production containers were not restarted.",
        "production_route_probe": {
            "path": "/api/control-plane/n8n-webhook-test/run",
            "status_code": 404,
            "meaning": "current production image does not include this code; rebuild/deploy is required before restart can apply it",
        },
    },
}

write("permission_leak_fix_report.json", permission_report)
write("execution_chain_realization_report.json", execution_report)
write("performance_fix_report.json", performance_report)
write("field_consistency_fix_report.json", field_report)
write("webhook_connection_failure_report.json", webhook_failure_report)
write("final_concurrency_report.json", concurrency_report)
write("final_system_readiness_report.json", readiness_report)
