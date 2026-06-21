from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.approval import (
    ApprovalDecisionRecord,
    ApprovalRequestRecord,
    ApprovalWorkflowRecord,
)
from backend.app.models.org_membership import OrgMembershipRecord
from backend.app.models.organization import OrganizationRecord
from backend.app.models.user import User

TEST_PASSWORD = "example-only-review-audit-password"
pytestmark = pytest.mark.integration


def create_review_audit_user(
    *,
    username: str,
    role: str,
    org_id: str,
) -> int:
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(TEST_PASSWORD),
            role=role,
            is_active=True,
            organization_id=org_id if role == "super_admin" else None,
        )
        db.add(user)
        db.flush()
        organization = db.get(OrganizationRecord, org_id)
        if organization is None:
            organization = OrganizationRecord(
                org_id=org_id,
                org_name=f"{username} 组织",
                org_type="store",
                owner_user_id=str(user.id),
                status="active",
                metadata_json={},
            )
            db.add(organization)
            db.flush()
        membership_role = "owner" if role == "owner" else "admin"
        db.add(
            OrgMembershipRecord(
                membership_id=f"mem_{user.id:032x}",
                user_id=str(user.id),
                org_id=org_id,
                role=membership_role,
                status="active",
            )
        )
        db.commit()
        return user.id


def auth_headers(client: TestClient, *, username: str) -> dict[str, str]:
    response = client.post(
        "/api/public/auth/login",
        json={"username": username, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    session_id = response.cookies.get("barong_ops_session")
    assert session_id
    return {"Cookie": f"barong_ops_session={session_id}"}


def seed_approval_decision(
    *,
    actor_id: int,
    approval_id: str,
    org_id: str,
    status: str,
    reason: str,
    module_key: str = "business.reviews",
    action_key: str = "business.reviews.decision",
) -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.add(
            ApprovalRequestRecord(
                org_id=org_id,
                approval_id=approval_id,
                execution_id=f"job-{approval_id}",
                module_key=module_key,
                adapter_key=f"{module_key}.adapter",
                action_key=action_key,
                requester_id=actor_id,
                request_time=now,
                risk_level="high",
                execution_type="real",
                category="feature",
                status=status,
                reason="Approval audit test request.",
                reviewer_id=actor_id,
                context_snapshot={},
                status_trace=[],
                request_payload={"category": "feature"},
            )
        )
        db.add(
            ApprovalWorkflowRecord(
                org_id=org_id,
                workflow_id=f"workflow-{approval_id}",
                approval_id=approval_id,
                execution_id=f"job-{approval_id}",
                state=status,
                workflow_created_at=now,
                workflow_updated_at=now,
                workflow_payload={},
            )
        )
        db.flush()
        db.add(
            ApprovalDecisionRecord(
                org_id=org_id,
                decision_id=f"decision-{approval_id}",
                approval_id=approval_id,
                workflow_id=f"workflow-{approval_id}",
                status=status,
                reason=reason,
                decision_source="user",
                actor_type="user",
                actor_role="admin",
                actor_id=actor_id,
                decision_time=now,
                decision_payload={
                    "status": status,
                    "reason": reason,
                    "decision_source": "user",
                },
            )
        )
        db.commit()


def test_review_audit_owner_cross_org_and_super_admin_scope(
    auth_client: TestClient,
) -> None:
    org_1 = "org_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    org_2 = "org_ffffffffffffffffffffffffffffffff"
    org_3 = "org_abababababababababababababababab"
    create_review_audit_user(
        username="review_audit_owner_1",
        role="owner",
        org_id=org_1,
    )
    admin_1 = create_review_audit_user(
        username="review_audit_admin_1",
        role="super_admin",
        org_id=org_1,
    )
    create_review_audit_user(
        username="review_audit_owner_2",
        role="owner",
        org_id=org_2,
    )
    admin_2 = create_review_audit_user(
        username="review_audit_admin_2",
        role="super_admin",
        org_id=org_2,
    )
    create_review_audit_user(
        username="review_audit_operator",
        role="operator",
        org_id=org_1,
    )
    create_review_audit_user(
        username="review_audit_empty_admin",
        role="super_admin",
        org_id=org_3,
    )
    seed_approval_decision(
        actor_id=admin_1,
        approval_id="review-audit-approved",
        org_id=org_1,
        status="approved",
        reason="Approved for audit test.",
    )
    seed_approval_decision(
        actor_id=admin_2,
        approval_id="review-audit-rejected",
        org_id=org_2,
        status="rejected",
        reason="Rejected because the audit test needs a reason.",
        module_key="admin.permissions",
        action_key="admin.permissions.manage",
    )

    owner_headers = auth_headers(auth_client, username="review_audit_owner_1")
    admin_headers = auth_headers(auth_client, username="review_audit_admin_1")
    operator_headers = auth_headers(auth_client, username="review_audit_operator")

    owner_orgs = auth_client.get(
        "/api/app/reviews/organizations",
        headers=owner_headers,
    )
    admin_orgs = auth_client.get(
        "/api/app/reviews/organizations",
        headers=admin_headers,
    )
    admin_cross_org = auth_client.get(
        f"/api/app/reviews/organizations/{org_2}/users",
        headers=admin_headers,
    )
    operator_orgs = auth_client.get(
        "/api/app/reviews/organizations",
        headers=operator_headers,
    )
    organization_catalog = auth_client.get(
        "/api/app/organizations?limit=100&offset=0",
        headers=owner_headers,
    )
    organization_user_catalog = auth_client.get(
        f"/api/app/users?organization_id={org_2}&limit=100&offset=0",
        headers=owner_headers,
    )
    module_registry = auth_client.get(
        "/api/app/reviews/module-registry",
        headers=owner_headers,
    )
    owner_users = auth_client.get(
        f"/api/app/reviews/organizations/{org_2}/users",
        headers=owner_headers,
    )
    owner_actions = auth_client.get(
        f"/api/app/reviews/organizations/{org_2}/users/{admin_2}/actions",
        headers=owner_headers,
    )
    owner_filtered_actions = auth_client.get(
        f"/api/app/reviews/organizations/{org_2}/users/{admin_2}/actions?review_module=admin.permissions",
        headers=owner_headers,
    )

    assert owner_orgs.status_code == 200, owner_orgs.text
    assert {item["organization_id"] for item in owner_orgs.json()["items"]} == {
        org_1,
        org_2,
        org_3,
    }
    empty_org = next(
        item for item in owner_orgs.json()["items"] if item["organization_id"] == org_3
    )
    assert empty_org["action_count"] == 0
    assert admin_orgs.status_code == 200, admin_orgs.text
    assert [item["organization_id"] for item in admin_orgs.json()["items"]] == [
        org_1
    ]
    assert admin_cross_org.status_code == 403
    assert operator_orgs.status_code == 403
    assert organization_catalog.status_code == 200, organization_catalog.text
    assert {
        item["org_id"] for item in organization_catalog.json()["items"]
    } == {
        org_1,
        org_2,
        org_3,
    }
    assert organization_user_catalog.status_code == 200, (
        organization_user_catalog.text
    )
    assert {
        item["username"] for item in organization_user_catalog.json()["items"]
    } == {
        "review_audit_admin_2",
    }
    assert module_registry.status_code == 200, module_registry.text
    registry_module_keys = {
        item["module_key"] for item in module_registry.json()["items"]
    }
    assert {"admin.permissions", "business.reviews"}.issubset(
        registry_module_keys
    )
    assert owner_users.status_code == 200, owner_users.text
    assert owner_users.json()["items"][0]["employee_name"] == "review_audit_admin_2"
    assert owner_actions.status_code == 200, owner_actions.text
    action = owner_actions.json()["items"][0]
    assert action["operation_type"] == "拒绝"
    assert action["approval_module"] == "权限"
    assert action["rejection_reason"] == "Rejected because the audit test needs a reason."
    assert owner_filtered_actions.status_code == 200, owner_filtered_actions.text
    assert owner_filtered_actions.json()["items"][0]["audit_id"] == (
        "decision-review-audit-rejected"
    )
