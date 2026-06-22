import os
import warnings
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.app.core.config import Settings, get_settings
from backend.app.core.security import hash_password
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.approval import (
    ApprovalDecisionRecord,
    ApprovalRequestRecord,
    ApprovalWorkflowRecord,
)
from backend.app.models.api_keys import ApiKeyModuleBindingRecord, ApiKeyRecord
from backend.app.models.artifact import Artifact
from backend.app.models.auth_session import AuthSession
from backend.app.models.context import ContextPacket
from backend.app.models.error import SystemError
from backend.app.models.execution_state import (
    CallbackStateRecord,
    CallbackStateTransitionRecord,
    DLQStateRecord,
    ExecutionCallbackRecord,
    ExecutionDLQRecord,
    ExecutionResultRecord,
)
from backend.app.models.job import AutomationJob, JobEvent
from backend.app.models.memory import (
    AgentMemoryAccessLog,
    MemoryEvent,
    MemorySummary,
)
from backend.app.models.module_binding import ModuleBindingRecord
from backend.app.models.module_control import ModuleControlStateRecord
from backend.app.models.operation_log import OperationLog
from backend.app.models.observability import (
    AnomalyEventRecord,
    AuditLogRecord,
    EventStreamRecord,
    ReplayJobRecord,
    StorageEventRecord,
)
from backend.app.models.ops import (
    OpsAlertDeliveryRecord,
    OpsAlertRecord,
    OpsCanaryRolloutRecord,
    OpsExecutionUnlockTokenRecord,
    OpsLiveGatePolicyRecord,
    OpsRollbackGuardRecord,
)
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.permission import (
    PermissionRegistry,
    RoleDefaultPermission,
    UserPermissionAssignment,
)
from backend.app.models.registry import (
    AgentRegistry,
    ModuleRegistry,
    WorkflowRegistry,
)
from backend.app.models.review import ReviewItem
from backend.app.models.security import SecurityRateLimitBucket, SecurityReplayNonce
from backend.app.models.shared_module import SharedModuleRecord
from backend.app.models.user import User
from backend.app.services.session_seen_buffer import clear_session_seen_buffer


UNIT_TEST_FILE_NAMES = frozenset(
    {
        "test_permission_migration.py",
    }
)
SYSTEM_TEST_FILE_NAMES = frozenset(
    {
        "test_alembic_config.py",
        "test_approval_workflow_engine.py",
        "test_db_config.py",
        "test_event_collector.py",
        "test_execution_flow_gate.py",
        "test_health.py",
        "test_sandbox_execution_bridge.py",
        "test_sandbox_execution_context.py",
        "test_sandbox_runtime_finalization.py",
        "test_schema_models.py",
        "test_workflow_registry_system.py",
    }
)
SCHEMA_BOOTSTRAP_SIGNALS = (
    "Base.metadata.create_all",
    "__table__.create(",
)
SYSTEM_SIGNALS = (
    "TestClient",
    "clear_event_buffer",
    "capture_audit_events",
)
INTEGRATION_SIGNALS = (
    "SessionLocal",
    "backend.app.db.session",
    "clean_auth_tables",
)
CATEGORY_MARKERS = frozenset(("unit", "integration", "system"))
SOURCE_CACHE: dict[Path, str] = {}


def _source_for_path(path: Path) -> str:
    if path not in SOURCE_CACHE:
        SOURCE_CACHE[path] = path.read_text(encoding="utf-8")
    return SOURCE_CACHE[path]


def _is_alembic_managed_test_db() -> bool:
    return os.environ.get("BARONG_TEST_DB_READY") == "1"


def _integration_db_skip_reason() -> str:
    return (
        "Integration tests require BARONG_TEST_DB_READY=1 after Alembic "
        "upgrade on an isolated PostgreSQL test database. Use "
        "scripts/run_backend_tests.sh integration or provide a reachable "
        "DATABASE_URL."
    )


def _assert_safe_test_database_url() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    lowered = database_url.lower()

    if any(
        blocked in lowered
        for blocked in ("production", "prod", "ops.barongyekhna.com")
    ):
        pytest.exit(
            "Refusing to run integration tests against a production-like "
            "DATABASE_URL.",
            returncode=2,
        )

    if not any(
        allowed in lowered
        for allowed in ("barong_test", "localhost", "127.0.0.1")
    ):
        pytest.exit(
            "Integration tests require an isolated test DATABASE_URL. "
            "Use scripts/run_backend_tests.sh integration.",
            returncode=2,
        )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "unit: backend unit tests that do not require a live database service",
    )
    config.addinivalue_line(
        "markers",
        "integration: backend tests requiring an Alembic-managed test database",
    )
    config.addinivalue_line(
        "markers",
        "system: broader system or legacy DB tests outside unit/integration CI lanes",
    )
    config.addinivalue_line(
        "markers",
        "slow: tests that are expected to take materially longer",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    marker_expression = session.config.option.markexpr or ""
    if "integration" not in marker_expression:
        return
    if not _is_alembic_managed_test_db():
        warnings.warn(_integration_db_skip_reason(), stacklevel=1)
        return
    _assert_safe_test_database_url()


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    del config
    for item in items:
        if any(item.get_closest_marker(marker) for marker in CATEGORY_MARKERS):
            continue

        path = Path(str(item.fspath))
        if path.name in UNIT_TEST_FILE_NAMES:
            item.add_marker(pytest.mark.unit)
            continue

        if path.name in SYSTEM_TEST_FILE_NAMES:
            item.add_marker(pytest.mark.system)
            continue

        source = _source_for_path(path)
        if any(signal in source for signal in SCHEMA_BOOTSTRAP_SIGNALS):
            item.add_marker(pytest.mark.system)
            continue

        if any(signal in source for signal in SYSTEM_SIGNALS):
            item.add_marker(pytest.mark.system)
            continue

        if any(signal in source for signal in INTEGRATION_SIGNALS):
            item.add_marker(pytest.mark.integration)
            continue

        item.add_marker(pytest.mark.unit)


def pytest_runtest_setup(item: pytest.Item) -> None:
    if not item.get_closest_marker("integration"):
        return

    if not _is_alembic_managed_test_db():
        pytest.skip(_integration_db_skip_reason())
    _assert_safe_test_database_url()

    source = _source_for_path(Path(str(item.fspath)))
    if any(signal in source for signal in SCHEMA_BOOTSTRAP_SIGNALS):
        pytest.fail("Integration tests must use Alembic schema, not create_all.")


def clear_auth_tables() -> None:
    clear_session_seen_buffer()
    if _is_alembic_managed_test_db():
        _assert_safe_test_database_url()
    else:
        database_url = os.environ.get("DATABASE_URL", "")
        lowered = database_url.lower()
        if not any(
            allowed in lowered
            for allowed in ("sqlite", "barong_test", "localhost", "127.0.0.1")
        ):
            pytest.skip(_integration_db_skip_reason())
        Base.metadata.create_all(bind=engine, checkfirst=True)
    with SessionLocal() as db:
        db.execute(delete(AgentMemoryAccessLog))
        db.execute(delete(ContextPacket))
        db.execute(delete(MemorySummary))
        db.execute(delete(MemoryEvent))
        db.execute(delete(SystemError))
        db.execute(delete(DLQStateRecord))
        db.execute(delete(ExecutionDLQRecord))
        db.execute(delete(ExecutionCallbackRecord))
        db.execute(delete(CallbackStateTransitionRecord))
        db.execute(delete(CallbackStateRecord))
        db.execute(delete(ExecutionResultRecord))
        db.execute(delete(ReviewItem))
        db.execute(delete(Artifact))
        db.execute(delete(ApprovalDecisionRecord))
        db.execute(delete(ApprovalWorkflowRecord))
        db.execute(delete(ApprovalRequestRecord))
        db.execute(delete(SharedModuleRecord))
        db.execute(delete(ApiKeyModuleBindingRecord))
        db.execute(delete(ApiKeyRecord))
        db.execute(delete(ModuleControlStateRecord))
        db.execute(delete(ModuleBindingRecord))
        db.execute(delete(JobEvent))
        db.execute(delete(OperationLog))
        db.execute(delete(AutomationJob))
        db.execute(delete(AuthSession))
        db.execute(delete(SecurityRateLimitBucket))
        db.execute(delete(SecurityReplayNonce))
        db.execute(delete(OpsAlertDeliveryRecord))
        db.execute(delete(OpsAlertRecord))
        db.execute(delete(OpsRollbackGuardRecord))
        db.execute(delete(OpsCanaryRolloutRecord))
        db.execute(delete(OpsExecutionUnlockTokenRecord))
        db.execute(delete(OpsLiveGatePolicyRecord))
        db.execute(delete(AnomalyEventRecord))
        db.execute(delete(ReplayJobRecord))
        db.execute(delete(AuditLogRecord))
        db.execute(delete(StorageEventRecord))
        db.execute(delete(EventStreamRecord))
        db.execute(delete(OrgMembershipRecord))
        db.execute(delete(OrganizationRecord))
        db.execute(delete(UserPermissionAssignment))
        db.execute(delete(RoleDefaultPermission))
        db.execute(delete(PermissionRegistry))
        db.execute(delete(AgentRegistry))
        db.execute(delete(WorkflowRegistry))
        db.execute(delete(ModuleRegistry))
        db.execute(delete(User))
        db.commit()


@pytest.fixture
def clean_auth_tables() -> None:
    clear_auth_tables()
    yield
    clear_auth_tables()


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        auth_session_expire_minutes=30,
        auth_session_cookie_path="/",
        auth_session_cookie_secure=False,
    )


@pytest.fixture
def auth_client(
    clean_auth_tables: None,
    test_settings: Settings,
) -> TestClient:
    app.dependency_overrides[get_settings] = lambda: test_settings
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def owner_client(auth_client: TestClient) -> TestClient:
    username = "f10_api_owner"
    password = "f10-example-only-owner-password"
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role="owner",
            is_active=True,
        )
        db.add(user)
        db.flush()
        organization = OrganizationRecord(
            org_id="org_11111111111111111111111111111111",
            org_name="Default Test Org",
            org_type="store",
            owner_user_id=str(user.id),
            status="active",
            metadata_json={},
        )
        db.add(organization)
        db.flush()
        db.add(
            OrgMembershipRecord(
                membership_id="mem_11111111111111111111111111111111",
                user_id=str(user.id),
                org_id="org_11111111111111111111111111111111",
                role="owner",
                status="active",
            )
        )
        db.commit()

    response = auth_client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return auth_client
