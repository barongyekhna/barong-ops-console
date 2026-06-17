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
from backend.app.models.artifact import Artifact
from backend.app.models.auth_session import AuthSession
from backend.app.models.context import ContextPacket
from backend.app.models.error import SystemError
from backend.app.models.execution_state import (
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
from backend.app.models.operation_log import OperationLog
from backend.app.models.observability import (
    AnomalyEventRecord,
    AuditLogRecord,
    EventStreamRecord,
    ReplayJobRecord,
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

def clear_auth_tables() -> None:
    Base.metadata.create_all(bind=engine, checkfirst=True)
    with SessionLocal() as db:
        db.execute(delete(AgentMemoryAccessLog))
        db.execute(delete(ContextPacket))
        db.execute(delete(MemorySummary))
        db.execute(delete(MemoryEvent))
        db.execute(delete(SystemError))
        db.execute(delete(ExecutionDLQRecord))
        db.execute(delete(ExecutionCallbackRecord))
        db.execute(delete(ExecutionResultRecord))
        db.execute(delete(ReviewItem))
        db.execute(delete(Artifact))
        db.execute(delete(ApprovalDecisionRecord))
        db.execute(delete(ApprovalWorkflowRecord))
        db.execute(delete(ApprovalRequestRecord))
        db.execute(delete(SharedModuleRecord))
        db.execute(delete(ModuleBindingRecord))
        db.execute(delete(JobEvent))
        db.execute(delete(OperationLog))
        db.execute(delete(AutomationJob))
        db.execute(delete(AuthSession))
        db.execute(delete(SecurityRateLimitBucket))
        db.execute(delete(SecurityReplayNonce))
        db.execute(delete(AnomalyEventRecord))
        db.execute(delete(ReplayJobRecord))
        db.execute(delete(AuditLogRecord))
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
        db.add(
            OrganizationRecord(
                org_id="org_11111111111111111111111111111111",
                org_name="Default Test Org",
                org_type="store",
                owner_user_id=str(user.id),
                status="active",
                metadata_json={},
            )
        )
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
