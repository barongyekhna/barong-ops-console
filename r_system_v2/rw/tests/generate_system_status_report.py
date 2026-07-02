"""Generate final R-W system status report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r_system_v2.rw.providers.keepa_provider import KeepaProvider


MOCK_E2E_REPORT = REPO_ROOT / "R_W_MOCK_E2E_REPORT.json"
AUDIT_REPORT = REPO_ROOT / "R_W_E2E_AUDIT_REPORT.json"
SYSTEM_STATUS_REPORT = REPO_ROOT / "SYSTEM_STATUS_REPORT.json"


def _read_report(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"success": False, "missing": True}
    return json.loads(path.read_text(encoding="utf-8"))


def run() -> dict[str, object]:
    mock_report = _read_report(MOCK_E2E_REPORT)
    audit_report = _read_report(AUDIT_REPORT)
    provider = KeepaProvider(force_mock=True)
    e2e_passed = bool(mock_report.get("success") and audit_report.get("success"))

    report: dict[str, object] = {
        "rw_initialized": True,
        "mock_mode_active": provider.mock_mode,
        "e2e_passed": e2e_passed,
        "deployment_ready": e2e_passed,
        "next_step": "await_key_binding",
        "target": "https://ops.barongyekhna.com",
        "scope": "R-W only",
        "real_keepa_api_used": False,
        "r_a_triggered": False,
        "storage_schema_ready": (REPO_ROOT / "r_system_v2" / "db" / "schema_rw.sql").exists(),
        "reports": {
            "mock_e2e": str(MOCK_E2E_REPORT),
            "e2e_audit": str(AUDIT_REPORT),
        },
    }

    SYSTEM_STATUS_REPORT.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
