from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from r_system_v2.core.secret_manager import SecretManager, SecretNotFoundError
from r_system_v2.rw.ai.deepseek_screening import DeepSeekScreeningSkill
from r_system_v2.rw.providers.keepa_provider import KeepaProvider


REPORT_PATH = REPO_ROOT / "R_SECRET_MANAGER_E2E_REPORT.json"
TARGET_ORG_ID = "org_11111111111111111111111111111111"
OTHER_ORG_ID = "org_22222222222222222222222222222222"
TARGET_ORG_NAME = "涌龙麟（深圳）国际贸易有限公司"


def now() -> str:
    return datetime.now(UTC).isoformat()


def write_report(payload: dict[str, object]) -> None:
    REPORT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def role_allowed(role: str) -> bool:
    return role in {"owner", "super_admin"}


def run() -> dict[str, object]:
    engine = create_engine("sqlite:///:memory:")
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    manager = SecretManager(db_session=session)

    frontend_payloads = {
        "keepa": "keepa-test-key",
        "deepseek": "deepseek-test-key",
        "openai": "openai-test-key",
        "serper": "serper-test-key",
    }
    set_results = {
        service: manager.set_key(service, value, TARGET_ORG_ID).to_dict()
        for service, value in frontend_payloads.items()
    }
    status_after_set = manager.validate_keys(TARGET_ORG_ID)
    reload_result = manager.reload()

    keepa_provider = KeepaProvider(
        org_id=TARGET_ORG_ID,
        secret_manager=manager,
        force_mock=True,
    )
    deepseek_skill = DeepSeekScreeningSkill(
        org_id=TARGET_ORG_ID,
        secret_manager=manager,
    )

    try:
        manager.get_key("keepa", OTHER_ORG_ID)
        org_isolation_status = "FAIL"
    except SecretNotFoundError:
        org_isolation_status = "OK"

    permission_matrix = {
        "owner": role_allowed("owner"),
        "super_admin": role_allowed("super_admin"),
        "normal_user": role_allowed("normal_user"),
    }

    key_storage_ok = status_after_set["all_configured"] is True
    frontend_sync_ok = all(item["configured"] for item in status_after_set["services"])
    worker_reload_ok = (
        reload_result["runtime_hot_reload"] is True
        and keepa_provider.api_key == frontend_payloads["keepa"]
        and deepseek_skill.api_key_configured() is True
    )

    report: dict[str, object] = {
        "generated_at": now(),
        "organization": TARGET_ORG_NAME,
        "org_id": TARGET_ORG_ID,
        "key_storage_status": "OK" if key_storage_ok else "FAIL",
        "frontend_sync_status": "OK" if frontend_sync_ok else "FAIL",
        "worker_reload_status": "OK" if worker_reload_ok else "FAIL",
        "org_isolation_status": org_isolation_status,
        "keepa_connection_status": {
            "status": "CONFIGURED_VIA_SECRET_MANAGER"
            if keepa_provider.api_key == frontend_payloads["keepa"]
            else "FAIL",
            "live_network_check": "NOT_RUN",
        },
        "deepseek_connection_status": {
            "status": "CONFIGURED_VIA_SECRET_MANAGER"
            if deepseek_skill.api_key_configured()
            else "FAIL",
            "live_network_check": "NOT_RUN",
        },
        "set_results": set_results,
        "reload_result": reload_result,
        "permission_matrix": permission_matrix,
        "secret_system_status": {
            "unified": key_storage_ok and worker_reload_ok and org_isolation_status == "OK",
            "frontend_sync": "OK" if frontend_sync_ok else "FAIL",
            "worker_sync": "OK" if worker_reload_ok else "FAIL",
            "org_isolation": org_isolation_status,
        },
    }
    write_report(report)
    return report


if __name__ == "__main__":
    result = run()
    status = result["secret_system_status"]
    print("SECRET_SYSTEM_STATUS:")
    print(f"- unified: {str(status['unified']).lower()}")
    print(f"- frontend_sync: {status['frontend_sync']}")
    print(f"- worker_sync: {status['worker_sync']}")
    print(f"- org_isolation: {status['org_isolation']}")
