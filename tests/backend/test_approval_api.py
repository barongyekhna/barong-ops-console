from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.approval import (
    ApprovalDecisionRecord,
    ApprovalRequestRecord,
    ApprovalWorkflowRecord,
)
from backend.app.models.user import User

TEST_PASSWORD = "example-only-approval-api-password"


def create_approval_user(
    *,
    username: str,
    role: str,
    password: str = TEST_PASSWORD,
) -> int:
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return user.id


def auth_headers(
    client: TestClient,
    *,
    username: str,
    password: str = TEST_PASSWORD,
) -> dict[str, str]:
    response = client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    session_id = response.cookies.get("barong_ops_session")
    assert session_id
    return {"Cookie": f"barong_ops_session={session_id}"}


def approval_payload(
    *,
    approval_id: str = "approval-api-1",
    execution_id: str = "execution-api-1",
) -> dict[str, object]:
    return {
        "approval_id": approval_id,
        "execution_id": execution_id,
        "module_key": "admin.users",
        "adapter_key": "admin.users.adapter",
        "action_key": "admin.users.manage",
        "risk_level": "high",
        "execution_type": "real",
        "reason": "Approval is required before execution can continue.",
    }


def test_owner_request_persists_workflow_and_decision(
    owner_client: TestClient,
) -> None:
    response = owner_client.post(
        "/api/app/approval/request",
        json=approval_payload(),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["approval"]["status"] == "pending"
    assert body["workflow"]["state"] == "pending"
    assert body["decisions"][0]["status"] == "pending"
    assert body["safety"]["no_execution"] is True
    assert body["safety"]["no_sandbox_call"] is True
    assert body["safety"]["no_external_provider"] is True

    with SessionLocal() as db:
        approval = db.scalar(
            select(ApprovalRequestRecord).where(
                ApprovalRequestRecord.approval_id == "approval-api-1"
            )
        )
        workflow = db.scalar(
            select(ApprovalWorkflowRecord).where(
                ApprovalWorkflowRecord.approval_id == "approval-api-1"
            )
        )
        decisions = list(
            db.scalars(
                select(ApprovalDecisionRecord)
                .where(ApprovalDecisionRecord.approval_id == "approval-api-1")
                .order_by(ApprovalDecisionRecord.id)
            )
        )

    assert approval is not None
    assert approval.status == "pending"
    assert workflow is not None
    assert workflow.state == "pending"
    assert [decision.status for decision in decisions] == ["pending"]


def test_admin_can_approve_pending_approval(
    auth_client: TestClient,
) -> None:
    create_approval_user(username="c12d_owner", role="owner")
    create_approval_user(username="c12d_admin", role="super_admin")
    owner_headers = auth_headers(auth_client, username="c12d_owner")
    admin_headers = auth_headers(auth_client, username="c12d_admin")

    created = auth_client.post(
        "/api/app/approval/request",
        json=approval_payload(
            approval_id="approval-api-admin",
            execution_id="execution-api-admin",
        ),
        headers=owner_headers,
    )
    approved = auth_client.post(
        "/api/app/approval/approval-api-admin/approve",
        json={"reason": "Admin approved the pending approval request."},
        headers=admin_headers,
    )

    assert created.status_code == 201, created.text
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval"]["status"] == "approved"
    assert approved.json()["workflow"]["state"] == "approved"
    assert approved.json()["permission_boundary"]["actor_role"] == "admin"

    with SessionLocal() as db:
        approval = db.scalar(
            select(ApprovalRequestRecord).where(
                ApprovalRequestRecord.approval_id == "approval-api-admin"
            )
        )
        decisions = list(
            db.scalars(
                select(ApprovalDecisionRecord)
                .where(
                    ApprovalDecisionRecord.approval_id
                    == "approval-api-admin"
                )
                .order_by(ApprovalDecisionRecord.id)
            )
        )

    assert approval is not None
    assert approval.status == "approved"
    assert [decision.status for decision in decisions] == [
        "pending",
        "approved",
    ]
    assert decisions[-1].actor_role == "admin"


def test_user_role_can_request_but_cannot_list_or_approve(
    auth_client: TestClient,
) -> None:
    create_approval_user(username="c12d_user", role="operator")
    user_headers = auth_headers(auth_client, username="c12d_user")

    created = auth_client.post(
        "/api/app/approval/request",
        json=approval_payload(
            approval_id="approval-api-user",
            execution_id="execution-api-user",
        ),
        headers=user_headers,
    )
    listed = auth_client.get("/api/app/approval/list", headers=user_headers)
    approved = auth_client.post(
        "/api/app/approval/approval-api-user/approve",
        json={"reason": "User should not be allowed to approve."},
        headers=user_headers,
    )

    assert created.status_code == 201, created.text
    assert created.json()["permission_boundary"]["actor_role"] == "user"
    assert listed.status_code == 403
    assert approved.status_code == 403
