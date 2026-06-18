from __future__ import annotations

import json
from pathlib import Path

from scripts import staging_stabilization as staging


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_json(relative_path: str) -> dict:
    return json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_fix041_staging_env_lock_is_deterministic_and_secret_safe() -> None:
    lock = _load_json("staging_env.lock")

    assert lock["lock_version"] == "PRE20-P-Batch10-FIX041-v1"
    assert lock["environment"] == "staging"
    assert lock["canonical_env_file"] == ".env.staging.example"
    assert lock["runtime_env_file"] == ".env.staging"
    assert lock["runtime_env_policy"]["must_be_git_ignored"] is True
    assert lock["dynamic_config_injection"]["runtime_env_drift_allowed"] is False
    assert lock["dynamic_config_injection"]["host_env_interpolation_allowed"] is False
    assert lock["docker_compose"]["pin"] == "1.29.2"
    assert all(guard["status"] == "passed" for guard in lock["drift_guards"])
    assert lock["canonical_env_nonsecret_values"]["OWNER_PASSWORD"] == "[redacted]"
    assert lock["canonical_env_nonsecret_values"]["POSTGRES_PASSWORD"] == "[redacted]"


def test_fix042_migration_manifest_locks_head_order_and_hashes() -> None:
    manifest = _load_json("migration_manifest.json")
    validation = staging.validate_migration_manifest(manifest)

    assert validation["status"] == "passed"
    assert manifest["alembic_head"] == "fix_be_06_modules_me_perf_001"
    assert manifest["head_locked"] is True
    assert manifest["migration_order"] == [
        "f07_core_001",
        "c05b_permissions_001",
        "c12d_approval_001",
        "c16_auth_sessions_001",
        "c16_fix4_login_lockout_001",
        "c16_adv_security_001",
        "c18_tenant_consistency_001",
        "execution_durable_state_001",
        "c17_durable_observability_001",
        "pre20_o_concurrency_perf_001",
        "pre20_o_ops_dr_001",
        "pre20_q_live_enable_gate_001",
        "fix_be_06_modules_me_perf_001",
    ]
    assert all(
        entry["version"] and entry["checksum"] and entry["applied_at"]
        for entry in manifest["migrations"]
    )


def test_fix043_fix044_contract_and_integration_reports_are_clean() -> None:
    contract = staging.build_contract_report()
    integration = _load_json("staging_integration_report.json")

    assert contract["status"] == "passed"
    assert contract["missing_endpoint"] == []
    assert contract["schema_mismatch"] == []
    assert contract["broken_proxy_allowlist"] == []
    assert integration["report_version"] == "PRE20-P-Batch10-FIX043-v1"
    assert all(check["status"] == "passed" for check in integration["checks"])
    assert {check["id"] for check in integration["checks"]}.issuperset(
        {
            "backend_api_health_contract",
            "auth_login_flow_contract",
            "permission_check_c05_contract",
            "c18_org_isolation_suite",
            "c17_event_write_read_suite",
            "db_migration_validation",
            "frontend_proxy_contract",
        }
    )


def test_fix045_staging_seed_is_idempotent_and_complete() -> None:
    seed = _read("staging_seed.sql")

    for required in (
        "INSERT INTO users",
        "INSERT INTO permission_registry",
        "INSERT INTO role_default_permissions",
        "INSERT INTO organizations",
        "INSERT INTO org_memberships",
        "INSERT INTO module_registry",
        "INSERT INTO module_bindings",
        "ON CONFLICT",
        "org_11111111111111111111111111111111",
        "staging.health",
        "staging.observability",
    ):
        assert required in seed
    assert ".env.production" not in seed
    assert "docker-compose.production" not in seed
    assert "c19" not in seed.lower()


def test_fix046_fix047_fix048_reports_cover_rollback_state_and_observability() -> None:
    consistency = _load_json("staging_consistency_report.json")
    rollback = _load_json("rollback_drill_report.json")
    observability = _load_json("staging_observability_report.json")

    assert consistency["status"] == "passed"
    assert consistency["state_enforcement"]["status"] == "passed"
    assert (
        consistency["state_enforcement"]["policy"]["memory_fallback_allowed_in_staging"]
        is False
    )
    assert rollback["report_version"] == "PRE20-P-Batch10-FIX046-v1"
    assert {check["id"] for check in rollback["checks"]}.issuperset(
        {
            "deploy_version_n_dry_run",
            "rollback_to_n_minus_1_dry_run",
            "db_state_verification",
            "api_health_verification",
            "frontend_load_verification",
            "c17_logs_consistency",
        }
    )
    assert observability["status"] == "passed"
    assert observability["pipeline"] == "event_streams -> anomaly_events -> alert_engine -> sink"
    assert all(check["status"] == "passed" for check in observability["checks"])
