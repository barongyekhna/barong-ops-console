from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r_system_v2.core.persistence_validator import PersistenceValidator


REPORT_PATH = REPO_ROOT / "R_W_FINAL_E2E_WITH_PERSISTENCE.json"


def now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def run_full_pipeline_audit() -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "rw_full_system_audit.py")],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    final_report_path = REPO_ROOT / "R_W_FINAL_SYSTEM_AUDIT.json"
    final_report = {}
    if final_report_path.exists():
        final_report = json.loads(final_report_path.read_text(encoding="utf-8"))
    return {
        "status": "PASS"
        if completed.returncode == 0 and final_report.get("deployment") == "ALLOWED"
        else "FAIL",
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "final_report": final_report,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    validator = PersistenceValidator(
        database_url=args.database_url or os.getenv("DATABASE_URL", ""),
        compose_file=Path(args.compose_file),
        postgres_service=args.postgres_service,
        backend_service=args.backend_service,
        postgres_volume=args.postgres_volume,
        use_docker_psql=args.use_docker_psql,
        apply_schema=args.apply_schema,
    )
    persistence = validator.validate(restart_backend=args.restart_backend)
    persistence_payload = persistence.to_dict()
    pre_audit_payload: dict[str, Any] = {
        "generated_at": now(),
        "persistence": persistence_payload,
        "persistence_write_status": persistence.write_read_cycle.status,
        "persistence_read_after_restart": persistence.read_after_restart.status,
        "db_volume_status": persistence.docker_volume.status,
        "full_pipeline_status": "NOT_STARTED",
        "full_pipeline_audit": None,
        "deployment_allowed": False,
    }
    write_json(REPORT_PATH, pre_audit_payload)

    full_pipeline = (
        run_full_pipeline_audit()
        if persistence.deployment_allowed
        else {
            "status": "FAIL",
            "blocked_reason": "persistence gate failed; full pipeline audit not started",
        }
    )
    deployment_allowed = bool(persistence.deployment_allowed and full_pipeline["status"] == "PASS")
    report: dict[str, Any] = {
        "generated_at": now(),
        "persistence": persistence_payload,
        "persistence_write_status": persistence.write_read_cycle.status,
        "persistence_read_after_restart": persistence.read_after_restart.status,
        "db_volume_status": persistence.docker_volume.status,
        "full_pipeline_status": full_pipeline["status"],
        "full_pipeline_audit": full_pipeline,
        "deployment_allowed": deployment_allowed,
        "deployment_command": "NOT_RUN",
        "direct_deploy_executed": False,
    }
    write_json(REPORT_PATH, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run R-W persistence deployment gate E2E.")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--compose-file", default=str(REPO_ROOT / "docker-compose.production.yml"))
    parser.add_argument("--postgres-service", default="console_postgres")
    parser.add_argument("--backend-service", default="console_backend")
    parser.add_argument("--postgres-volume", default="console_postgres_data")
    parser.add_argument("--use-docker-psql", action="store_true")
    parser.add_argument("--restart-backend", action="store_true")
    parser.add_argument("--apply-schema", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    result = run(parse_args())
    print("PERSISTENCE_GATE_STATUS:")
    print(
        "- persistence_verified: "
        f"{'PASS' if result['persistence']['persistence_verified'] else 'FAIL'}"
    )
    print(f"- e2e_status: {result['full_pipeline_status']}")
    print(f"- deployment_allowed: {str(result['deployment_allowed']).upper()}")
