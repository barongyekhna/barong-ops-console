import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.operation_log import OperationLog
from backend.app.models.permission import UserPermissionAssignment
from backend.app.models.user import User
from backend.app.services.permission_service import (
    HIGH_RISK_CONFIRMATION_TEXT,
    upsert_permission_registry,
    upsert_role_default_permission,
)

TEST_PASSWORD = "example-only-c06b-permission-password"


def create_permission_assignment_user(
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


def seed_registry() -> None:
    with SessionLocal() as db:
        upsert_permission_registry(db)


def login_token(
    client: TestClient,
    *,
    username: str,
    password: str = TEST_PASSWORD,
) -> str:
    response = client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    session_id = response.cookies.get("barong_ops_session")
    assert session_id
    return session_id


def auth_headers(token: str) -> dict[str, str]:
    return {"Cookie": f"barong_ops_session={token}"}


def permission_operation_logs() -> list[OperationLog]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(OperationLog)
                .where(OperationLog.action.like("permission.assignment.%"))
                .order_by(OperationLog.id)
            )
        )


def grant_assignment(
    client: TestClient,
    *,
    owner_token: str,
    user_id: int,
    permission_key: str = "jobs.read",
    reason: str = "C06B test grant.",
    **extra: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "permission_key": permission_key,
        "reason": reason,
    }
    payload.update(extra)
    response = client.post(
        f"/api/app/permissions/users/{user_id}/assignments",
        headers=auth_headers(owner_token),
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


def test_owner_lists_assignments_and_owner_target_full_access(
    auth_client: TestClient,
) -> None:
    seed_registry()
    owner_id = create_permission_assignment_user(
        username="c06b_owner_list",
        role="owner",
    )
    viewer_id = create_permission_assignment_user(
        username="c06b_viewer_list",
        role="viewer",
    )
    owner_token = login_token(auth_client, username="c06b_owner_list")
    grant_assignment(
        auth_client,
        owner_token=owner_token,
        user_id=viewer_id,
    )

    response = auth_client.get(
        f"/api/app/permissions/users/{viewer_id}/assignments",
        headers=auth_headers(owner_token),
    )
    owner_response = auth_client.get(
        f"/api/app/permissions/users/{owner_id}/assignments",
        headers=auth_headers(owner_token),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == viewer_id
    assert payload["is_owner_full_access"] is False
    assert len(payload["assignments"]) == 1
    assignment = payload["assignments"][0]
    assert assignment["permission_key"] == "jobs.read"
    assert assignment["permission_name"] == "Read jobs"
    assert assignment["scope_type"] == "global"
    assert assignment["scope_id"] == "*"
    assert assignment["enabled"] is True
    assert assignment["effective"] is True
    assert "password_hash" not in json.dumps(payload, sort_keys=True)
    assert "token" not in json.dumps(payload, sort_keys=True).lower()

    assert owner_response.status_code == 200
    owner_payload = owner_response.json()
    assert owner_payload["user_id"] == owner_id
    assert owner_payload["is_owner_full_access"] is True
    assert owner_payload["assignments"] == []
    assert "assignment" in owner_payload["owner_full_access_note"]


def test_non_owner_and_super_admin_cannot_manage_assignments(
    auth_client: TestClient,
) -> None:
    seed_registry()
    owner_id = create_permission_assignment_user(
        username="c06b_owner_access",
        role="owner",
    )
    viewer_id = create_permission_assignment_user(
        username="c06b_viewer_access",
        role="viewer",
    )
    super_admin_id = create_permission_assignment_user(
        username="c06b_super_admin_access",
        role="super_admin",
    )
    owner_token = login_token(auth_client, username="c06b_owner_access")
    viewer_token = login_token(auth_client, username="c06b_viewer_access")
    super_admin_token = login_token(
        auth_client,
        username="c06b_super_admin_access",
    )
    granted = grant_assignment(
        auth_client,
        owner_token=owner_token,
        user_id=viewer_id,
    )
    assignment_id = granted["assignment"]["id"]

    for token in (viewer_token, super_admin_token):
        list_response = auth_client.get(
            f"/api/app/permissions/users/{viewer_id}/assignments",
            headers=auth_headers(token),
        )
        grant_response = auth_client.post(
            f"/api/app/permissions/users/{viewer_id}/assignments",
            headers=auth_headers(token),
            json={"permission_key": "jobs.create", "reason": "blocked"},
        )
        update_response = auth_client.patch(
            f"/api/app/permissions/users/{viewer_id}/assignments/{assignment_id}",
            headers=auth_headers(token),
            json={"enabled": False, "reason": "blocked"},
        )
        revoke_response = auth_client.request(
            "DELETE",
            f"/api/app/permissions/users/{viewer_id}/assignments/{assignment_id}",
            headers=auth_headers(token),
            json={"reason": "blocked"},
        )

        assert list_response.status_code == 403
        assert grant_response.status_code == 403
        assert update_response.status_code == 403
        assert revoke_response.status_code == 403

    assert owner_id != super_admin_id


def test_owner_grant_validation_and_permissions_me_effect(
    auth_client: TestClient,
) -> None:
    seed_registry()
    owner_id = create_permission_assignment_user(
        username="c06b_owner_grant",
        role="owner",
    )
    viewer_id = create_permission_assignment_user(
        username="c06b_viewer_grant",
        role="viewer",
    )
    owner_token = login_token(auth_client, username="c06b_owner_grant")
    viewer_token = login_token(auth_client, username="c06b_viewer_grant")

    granted = grant_assignment(
        auth_client,
        owner_token=owner_token,
        user_id=viewer_id,
        permission_key="jobs.read",
    )
    assignment = granted["assignment"]
    me_response = auth_client.get(
        "/api/app/permissions/me",
        headers=auth_headers(viewer_token),
    )
    duplicate = auth_client.post(
        f"/api/app/permissions/users/{viewer_id}/assignments",
        headers=auth_headers(owner_token),
        json={"permission_key": "jobs.read", "reason": "duplicate"},
    )
    missing_permission = auth_client.post(
        f"/api/app/permissions/users/{viewer_id}/assignments",
        headers=auth_headers(owner_token),
        json={"permission_key": "jobs.archive", "reason": "missing"},
    )
    wildcard = auth_client.post(
        f"/api/app/permissions/users/{viewer_id}/assignments",
        headers=auth_headers(owner_token),
        json={"permission_key": "*", "reason": "wildcard"},
    )
    owner_target = auth_client.post(
        f"/api/app/permissions/users/{owner_id}/assignments",
        headers=auth_headers(owner_token),
        json={"permission_key": "jobs.read", "reason": "owner target"},
    )

    assert assignment["permission_key"] == "jobs.read"
    assert assignment["granted_by_user_id"] == owner_id
    assert me_response.status_code == 200
    assert "jobs.read" in me_response.json()["permissions"]["permission_keys"]
    assert duplicate.status_code == 409
    assert missing_permission.status_code == 400
    assert wildcard.status_code == 400
    assert owner_target.status_code == 400


def test_high_risk_grant_update_revoke_require_reason_confirmation_and_log(
    auth_client: TestClient,
) -> None:
    seed_registry()
    create_permission_assignment_user(
        username="c06b_owner_high_risk",
        role="owner",
    )
    viewer_id = create_permission_assignment_user(
        username="c06b_viewer_high_risk",
        role="viewer",
    )
    owner_token = login_token(auth_client, username="c06b_owner_high_risk")

    missing_confirmation = auth_client.post(
        f"/api/app/permissions/users/{viewer_id}/assignments",
        headers=auth_headers(owner_token),
        json={"permission_key": "permissions.manage"},
    )
    granted = grant_assignment(
        auth_client,
        owner_token=owner_token,
        user_id=viewer_id,
        permission_key="permissions.manage",
        reason="Temporary permission administration coverage.",
        confirm_high_risk=True,
        confirmation_text=HIGH_RISK_CONFIRMATION_TEXT,
    )
    assignment_id = granted["assignment"]["id"]
    disabled = auth_client.patch(
        f"/api/app/permissions/users/{viewer_id}/assignments/{assignment_id}",
        headers=auth_headers(owner_token),
        json={
            "enabled": False,
            "reason": "Pause high-risk access.",
        },
    )
    enable_without_confirmation = auth_client.patch(
        f"/api/app/permissions/users/{viewer_id}/assignments/{assignment_id}",
        headers=auth_headers(owner_token),
        json={"enabled": True, "reason": "Resume high-risk access."},
    )
    enabled = auth_client.patch(
        f"/api/app/permissions/users/{viewer_id}/assignments/{assignment_id}",
        headers=auth_headers(owner_token),
        json={
            "enabled": True,
            "reason": "Resume high-risk access.",
            "confirm_high_risk": True,
            "confirmation_text": HIGH_RISK_CONFIRMATION_TEXT,
        },
    )
    revoke_without_reason = auth_client.request(
        "DELETE",
        f"/api/app/permissions/users/{viewer_id}/assignments/{assignment_id}",
        headers=auth_headers(owner_token),
        json={},
    )
    revoked = auth_client.request(
        "DELETE",
        f"/api/app/permissions/users/{viewer_id}/assignments/{assignment_id}",
        headers=auth_headers(owner_token),
        json={"reason": "High-risk access no longer needed."},
    )

    assert missing_confirmation.status_code == 400
    assert granted["assignment"]["high_risk"] is True
    assert granted["assignment"]["risk_level"] == "critical"
    assert disabled.status_code == 200
    assert disabled.json()["assignment"]["enabled"] is False
    assert enable_without_confirmation.status_code == 400
    assert enabled.status_code == 200
    assert revoke_without_reason.status_code == 400
    assert revoked.status_code == 200
    assert revoked.json()["assignment"]["enabled"] is False

    logs = permission_operation_logs()
    success_actions = {
        log.action
        for log in logs
        if log.result == "success"
        and log.details["permission_key"] == "permissions.manage"
    }
    assert {
        "permission.assignment.grant",
        "permission.assignment.update",
        "permission.assignment.revoke",
    }.issubset(success_actions)
    grant_log = next(
        log
        for log in logs
        if log.action == "permission.assignment.grant"
        and log.result == "success"
        and log.details["permission_key"] == "permissions.manage"
    )
    assert grant_log.details["risk_level"] == "critical"
    assert grant_log.details["confirmation_provided"] is True
    assert grant_log.details["reason"] == (
        "Temporary permission administration coverage."
    )


def test_owner_updates_assignment_and_effective_permissions(
    auth_client: TestClient,
) -> None:
    seed_registry()
    create_permission_assignment_user(
        username="c06b_owner_update",
        role="owner",
    )
    viewer_id = create_permission_assignment_user(
        username="c06b_viewer_update",
        role="viewer",
    )
    other_user_id = create_permission_assignment_user(
        username="c06b_other_update",
        role="operator",
    )
    owner_token = login_token(auth_client, username="c06b_owner_update")
    viewer_token = login_token(auth_client, username="c06b_viewer_update")
    granted = grant_assignment(
        auth_client,
        owner_token=owner_token,
        user_id=viewer_id,
        permission_key="jobs.read",
    )
    assignment_id = granted["assignment"]["id"]

    disabled = auth_client.patch(
        f"/api/app/permissions/users/{viewer_id}/assignments/{assignment_id}",
        headers=auth_headers(owner_token),
        json={"enabled": False, "reason": "Disable for C06B test."},
    )
    disabled_me = auth_client.get(
        "/api/app/permissions/me",
        headers=auth_headers(viewer_token),
    )
    enabled_scoped = auth_client.patch(
        f"/api/app/permissions/users/{viewer_id}/assignments/{assignment_id}",
        headers=auth_headers(owner_token),
        json={
            "enabled": True,
            "scope_type": "module",
            "scope_id": "jobs",
            "reason": "Enable module-scoped access.",
        },
    )
    expired_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    expired = auth_client.patch(
        f"/api/app/permissions/users/{viewer_id}/assignments/{assignment_id}",
        headers=auth_headers(owner_token),
        json={
            "expires_at": expired_at,
            "reason": "Expire assignment for C06B test.",
        },
    )
    expired_me = auth_client.get(
        "/api/app/permissions/me",
        headers=auth_headers(viewer_token),
    )
    mismatched_user = auth_client.patch(
        f"/api/app/permissions/users/{other_user_id}/assignments/{assignment_id}",
        headers=auth_headers(owner_token),
        json={"enabled": False, "reason": "wrong user"},
    )
    permission_key_update = auth_client.patch(
        f"/api/app/permissions/users/{viewer_id}/assignments/{assignment_id}",
        headers=auth_headers(owner_token),
        json={"permission_key": "jobs.create", "reason": "not allowed"},
    )

    assert disabled.status_code == 200
    assert disabled.json()["assignment"]["enabled"] is False
    assert "jobs.read" not in disabled_me.json()["permissions"]["permission_keys"]
    assert enabled_scoped.status_code == 200
    assert enabled_scoped.json()["assignment"]["scope_type"] == "module"
    assert enabled_scoped.json()["assignment"]["scope_id"] == "jobs"
    assert expired.status_code == 200
    assert expired.json()["assignment"]["effective"] is False
    assert "jobs.read" not in expired_me.json()["permissions"]["permission_keys"]
    assert mismatched_user.status_code == 404
    assert permission_key_update.status_code == 400


def test_revoke_soft_disables_assignment_removes_effective_permission_and_logs(
    auth_client: TestClient,
) -> None:
    seed_registry()
    create_permission_assignment_user(
        username="c06b_owner_revoke",
        role="owner",
    )
    viewer_id = create_permission_assignment_user(
        username="c06b_viewer_revoke",
        role="viewer",
    )
    owner_token = login_token(auth_client, username="c06b_owner_revoke")
    viewer_token = login_token(auth_client, username="c06b_viewer_revoke")
    granted = grant_assignment(
        auth_client,
        owner_token=owner_token,
        user_id=viewer_id,
        permission_key="jobs.create",
    )
    assignment_id = granted["assignment"]["id"]

    revoked = auth_client.request(
        "DELETE",
        f"/api/app/permissions/users/{viewer_id}/assignments/{assignment_id}",
        headers=auth_headers(owner_token),
        json={"reason": "C06B revoke test."},
    )
    me_response = auth_client.get(
        "/api/app/permissions/me",
        headers=auth_headers(viewer_token),
    )

    assert revoked.status_code == 200
    assert revoked.json()["assignment"]["enabled"] is False
    assert "jobs.create" not in me_response.json()["permissions"]["permission_keys"]
    with SessionLocal() as db:
        stored = db.get(UserPermissionAssignment, assignment_id)
        assert stored is not None
        assert stored.is_enabled is False
    logs = permission_operation_logs()
    revoke_logs = [
        log
        for log in logs
        if log.action == "permission.assignment.revoke"
        and log.result == "success"
    ]
    assert revoke_logs
    assert revoke_logs[-1].details["before"]["enabled"] is True
    assert revoke_logs[-1].details["after"]["enabled"] is False


def test_security_boundaries_remain_owner_only_without_role_default_grants(
    auth_client: TestClient,
) -> None:
    seed_registry()
    create_permission_assignment_user(
        username="c06b_owner_security",
        role="owner",
    )
    super_admin_id = create_permission_assignment_user(
        username="c06b_super_admin_security",
        role="super_admin",
    )
    with SessionLocal() as db:
        upsert_role_default_permission(
            db,
            role="super_admin",
            permission_key="permissions.manage",
        )

    owner_token = login_token(auth_client, username="c06b_owner_security")
    super_admin_token = login_token(
        auth_client,
        username="c06b_super_admin_security",
    )
    super_admin_me = auth_client.get(
        "/api/app/permissions/me",
        headers=auth_headers(super_admin_token),
    )
    super_admin_grant = auth_client.post(
        f"/api/app/permissions/users/{super_admin_id}/assignments",
        headers=auth_headers(super_admin_token),
        json={"permission_key": "jobs.read", "reason": "blocked"},
    )
    super_admin_users = auth_client.get(
        "/api/app/users",
        headers=auth_headers(super_admin_token),
    )
    auth_register = auth_client.post(
        "/api/public/auth/register",
        json={
            "username": "blocked_c06b_register",
            "password": "example-only-register-password",
        },
    )
    owner_users = auth_client.get("/api/app/users", headers=auth_headers(owner_token))

    assert super_admin_me.status_code == 200
    assert super_admin_me.json()["permissions"]["permission_keys"] == []
    assert super_admin_grant.status_code == 403
    assert super_admin_users.status_code == 403
    assert auth_register.status_code == 404
    assert owner_users.status_code == 200
