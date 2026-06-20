from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.approval import (
    ApprovalDecisionRecord,
    ApprovalRequestRecord,
    ApprovalWorkflowRecord,
)
from backend.app.models.observability import AuditLogRecord
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.permission import UserPermissionAssignment
from backend.app.models.user import User
from backend.app.services.permission_service import upsert_permission_registry

TEST_PASSWORD = "example-only-approval-api-password"


def create_approval_user(
    *,
    username: str,
    role: str,
    password: str = TEST_PASSWORD,
    org_id: str | None = None,
) -> int:
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.flush()
        resolved_org_id = org_id or f"org_{user.id:032x}"
        organization = db.get(OrganizationRecord, resolved_org_id)
        if organization is None:
            organization = OrganizationRecord(
                org_id=resolved_org_id,
                org_name=f"{username} Org",
                org_type="store",
                owner_user_id=str(user.id),
                status="active",
                metadata_json={},
            )
            db.add(organization)
        membership_role = (
            "owner"
            if role == "owner"
            else "admin"
            if role in {"admin", "super_admin", "module_admin"}
            else "member"
        )
        db.add(
            OrgMembershipRecord(
                membership_id=f"mem_{user.id:032x}",
                user_id=str(user.id),
                org_id=resolved_org_id,
                role=membership_role,
                status="active",
            )
        )
        db.commit()
        return user.id


def grant_artifacts_read(user_id: int) -> None:
    with SessionLocal() as db:
        upsert_permission_registry(db)
        db.add(
            UserPermissionAssignment(
                user_id=user_id,
                permission_key="artifacts.read",
                scope_type="global",
                scope_key="*",
                reason="Approval visibility test.",
                is_enabled=True,
            )
        )
        db.commit()


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
    module_key: str = "business.artifacts",
    adapter_key: str = "business.artifacts.adapter",
    action_key: str = "business.artifacts.prepare",
) -> dict[str, object]:
    return {
        "approval_id": approval_id,
        "execution_id": execution_id,
        "module_key": module_key,
        "adapter_key": adapter_key,
        "action_key": action_key,
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
    assert body["approval"]["category"] == "feature"
    assert body["approval"]["organization_id"] is not None
    assert body["display"]["category_label"] == "功能审批"
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
    assert approval.category == "feature"
    assert workflow is not None
    assert workflow.state == "pending"
    assert [decision.status for decision in decisions] == ["pending"]


def test_admin_can_approve_pending_approval(
    auth_client: TestClient,
) -> None:
    org_id = "org_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    create_approval_user(username="c12d_owner", role="owner", org_id=org_id)
    create_approval_user(username="c12d_admin", role="super_admin", org_id=org_id)
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
        audit_logs = list(
            db.scalars(
                select(AuditLogRecord).where(
                    AuditLogRecord.action == "approval.approved"
                )
            )
        )

    assert approval is not None
    assert approval.status == "approved"
    assert [decision.status for decision in decisions] == [
        "pending",
        "approved",
    ]
    assert decisions[-1].actor_role == "admin"
    assert len(audit_logs) == 1
    assert audit_logs[0].payload["approval_action"] == "approve"
    assert audit_logs[0].payload["module"] == "business.artifacts"


def test_user_role_lists_only_permitted_feature_module_and_cannot_approve(
    auth_client: TestClient,
) -> None:
    org_id = "org_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    user_id = create_approval_user(
        username="c12d_user",
        role="operator",
        org_id=org_id,
    )
    create_approval_user(username="c12d_user_owner", role="owner", org_id=org_id)
    grant_artifacts_read(user_id)
    user_headers = auth_headers(auth_client, username="c12d_user")
    owner_headers = auth_headers(auth_client, username="c12d_user_owner")

    created = auth_client.post(
        "/api/app/approval/request",
        json=approval_payload(
            approval_id="approval-api-user",
            execution_id="execution-api-user",
        ),
        headers=owner_headers,
    )
    listed = auth_client.get("/api/app/approval/list", headers=user_headers)
    approved = auth_client.post(
        "/api/app/approval/approval-api-user/approve",
        json={},
        headers=user_headers,
    )

    assert created.status_code == 201, created.text
    assert listed.status_code == 200, listed.text
    assert listed.json()["count"] == 1
    assert listed.json()["items"][0]["display"]["category_label"] == "功能审批"
    assert approved.status_code == 403


def test_control_plane_approval_is_owner_only(
    auth_client: TestClient,
) -> None:
    org_id = "org_cccccccccccccccccccccccccccccccc"
    create_approval_user(username="c12d_cp_owner", role="owner", org_id=org_id)
    create_approval_user(username="c12d_cp_admin", role="super_admin", org_id=org_id)
    owner_headers = auth_headers(auth_client, username="c12d_cp_owner")
    admin_headers = auth_headers(auth_client, username="c12d_cp_admin")

    created = auth_client.post(
        "/api/app/approval/request",
        json=approval_payload(
            approval_id="approval-api-control",
            execution_id="execution-api-control",
            module_key="admin.permissions",
            adapter_key="admin.permissions.adapter",
            action_key="admin.permissions.manage",
        ),
        headers=owner_headers,
    )
    admin_list = auth_client.get("/api/app/approval/list", headers=admin_headers)
    admin_detail = auth_client.get(
        "/api/app/approval/approval-api-control",
        headers=admin_headers,
    )
    owner_detail = auth_client.get(
        "/api/app/approval/approval-api-control",
        headers=owner_headers,
    )

    assert created.status_code == 201, created.text
    assert created.json()["approval"]["category"] == "control_plane"
    assert admin_list.status_code == 200
    assert admin_list.json()["items"] == []
    assert admin_detail.status_code == 403
    assert owner_detail.status_code == 200
    assert owner_detail.json()["display"]["category_label"] == "主控审批"


def test_reject_requires_long_reason_and_audits_success(
    auth_client: TestClient,
) -> None:
    org_id = "org_dddddddddddddddddddddddddddddddd"
    create_approval_user(username="c12d_reject_owner", role="owner", org_id=org_id)
    create_approval_user(
        username="c12d_reject_admin",
        role="super_admin",
        org_id=org_id,
    )
    owner_headers = auth_headers(auth_client, username="c12d_reject_owner")
    admin_headers = auth_headers(auth_client, username="c12d_reject_admin")

    created = auth_client.post(
        "/api/app/approval/request",
        json=approval_payload(
            approval_id="approval-api-reject",
            execution_id="execution-api-reject",
        ),
        headers=owner_headers,
    )
    short_reject = auth_client.post(
        "/api/app/approval/approval-api-reject/reject",
        json={"reason": "too short"},
        headers=admin_headers,
    )
    rejected = auth_client.post(
        "/api/app/approval/approval-api-reject/reject",
        json={"reason": "This rejection reason is long enough."},
        headers=admin_headers,
    )

    assert created.status_code == 201, created.text
    assert short_reject.status_code == 422
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["approval"]["status"] == "rejected"

    with SessionLocal() as db:
        audit_logs = list(
            db.scalars(
                select(AuditLogRecord).where(
                    AuditLogRecord.action == "approval.rejected"
                )
            )
        )
    assert len(audit_logs) == 1
    assert audit_logs[0].payload["approval_action"] == "reject"
    assert audit_logs[0].payload["reason"] == "This rejection reason is long enough."
