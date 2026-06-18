import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from backend.app.core.security import (
    hash_session_id,
    hash_password,
)
from backend.app.db.session import SessionLocal, engine
from backend.app.models.auth_session import AuthSession
from backend.app.models.operation_log import OperationLog
from backend.app.models.user import User
from backend.app.services.auth_service import (
    AuditContext,
    clear_session_identity_cache,
    login as login_user,
    validate_session,
)
from backend.app.services.session_seen_buffer import (
    clear_session_seen_buffer,
    flush_session_seen_updates,
    queue_session_seen,
)

USERNAME = "api_owner"
PASSWORD = "example-only-api-owner-password"
OPERATOR_USERNAME = "api_operator"
OPERATOR_PASSWORD = "example-only-api-operator-password"


def create_test_owner(*, is_active: bool = True) -> int:
    with SessionLocal() as db:
        owner = User(
            username=USERNAME,
            password_hash=hash_password(PASSWORD),
            role="owner",
            is_active=is_active,
        )
        db.add(owner)
        db.commit()
        return owner.id


def create_test_user(
    *,
    username: str = OPERATOR_USERNAME,
    password: str = OPERATOR_PASSWORD,
    role: str = "operator",
    is_active: bool = True,
) -> int:
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        return user.id


def login(client: TestClient):
    response = client.post(
        "/api/public/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response


def session_cookie(response) -> str:
    session_id = response.cookies.get("barong_ops_session")
    assert session_id
    return session_id


def service_audit_context(request_id: str) -> AuditContext:
    return AuditContext(request_id=request_id, ip_address=None, user_agent=None)


def create_service_session(settings) -> str:
    with SessionLocal() as db:
        result = login_user(
            db,
            username=USERNAME,
            password=PASSWORD,
            settings=settings,
            audit=service_audit_context("test-service-login"),
        )
        return result.session_id


def aware(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def test_login_returns_session_cookie_updates_user_and_writes_audit_log(
    auth_client: TestClient,
) -> None:
    owner_id = create_test_owner()

    response = login(auth_client)
    payload = response.json()
    raw_session_id = session_cookie(response)

    assert "access_token" not in payload
    assert "token_type" not in payload
    assert payload["user"]["id"] == owner_id
    assert payload["user"]["username"] == USERNAME
    assert payload["user"]["role"] == "owner"
    assert payload["user"]["is_active"] is True
    assert "password_hash" not in json.dumps(payload)

    with SessionLocal() as db:
        owner = db.get(User, owner_id)
        auth_session = db.scalar(
            select(AuthSession).where(AuthSession.user_id == owner_id)
        )
        operation_log = db.scalar(
            select(OperationLog).where(
                OperationLog.action == "auth.login",
                OperationLog.result == "success",
            )
        )

    assert owner is not None
    assert owner.last_login_at is not None
    assert auth_session is not None
    assert auth_session.session_id_hash == hash_session_id(raw_session_id)
    assert auth_session.invalidated_at is None
    assert auth_session.expires_at is not None
    assert operation_log is not None
    assert operation_log.actor_id == str(owner_id)


def test_login_failure_is_uniform_and_audited_without_secrets(
    auth_client: TestClient,
) -> None:
    owner_id = create_test_owner()
    with SessionLocal() as db:
        owner = db.get(User, owner_id)
        assert owner is not None
        stored_hash = owner.password_hash

    wrong_password = "example-only-wrong-password"
    wrong_password_response = auth_client.post(
        "/api/public/auth/login",
        json={"username": USERNAME, "password": wrong_password},
    )
    unknown_user_response = auth_client.post(
        "/api/public/auth/login",
        json={"username": "unknown_owner", "password": wrong_password},
    )

    assert wrong_password_response.status_code == 401
    assert unknown_user_response.status_code == 401
    assert wrong_password_response.json() == unknown_user_response.json()

    with SessionLocal() as db:
        operation_logs = list(
            db.scalars(
                select(OperationLog)
                .where(
                    OperationLog.action == "auth.login",
                    OperationLog.result == "failure",
                )
                .order_by(OperationLog.id)
            )
        )

    assert len(operation_logs) == 2
    serialized_logs = json.dumps(
        [operation_log.details for operation_log in operation_logs],
        sort_keys=True,
    )
    assert wrong_password not in serialized_logs
    assert PASSWORD not in serialized_logs
    assert stored_hash not in serialized_logs
    assert "password_hash" not in serialized_logs


def test_inactive_user_cannot_login(auth_client: TestClient) -> None:
    create_test_owner(is_active=False)

    response = auth_client.post(
        "/api/public/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password."


def test_active_non_owner_user_can_login(auth_client: TestClient) -> None:
    user_id = create_test_user()

    response = auth_client.post(
        "/api/public/auth/login",
        json={"username": OPERATOR_USERNAME, "password": OPERATOR_PASSWORD},
    )

    assert response.status_code == 200
    assert session_cookie(response)
    payload = response.json()
    assert "access_token" not in payload
    assert payload["user"]["id"] == user_id
    assert payload["user"]["role"] == "operator"
    assert "password_hash" not in json.dumps(payload)


def test_auth_me_returns_current_user(auth_client: TestClient) -> None:
    owner_id = create_test_owner()
    login(auth_client)

    response = auth_client.get("/api/public/auth/me")

    assert response.status_code == 200
    assert response.json()["id"] == owner_id
    assert response.json()["username"] == USERNAME
    assert "permissions" not in response.json()
    assert "password_hash" not in response.json()


def test_auth_me_fast_path_uses_one_read_query_without_permissions(
    auth_client: TestClient,
) -> None:
    owner_id = create_test_owner()
    login(auth_client)
    clear_session_identity_cache()

    statements: list[str] = []

    def collect_statement(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:
        del conn, cursor, parameters, context, executemany
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", collect_statement)
    try:
        response = auth_client.get("/api/public/auth/me")
    finally:
        event.remove(engine, "before_cursor_execute", collect_statement)

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == owner_id
    assert "permissions" not in payload

    write_statements = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]
    assert write_statements == []

    data_statements = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ]
    assert len(data_statements) <= 1
    assert not any("permission" in statement.lower() for statement in statements)
    assert not any("org_memberships" in statement.lower() for statement in statements)
    assert not any("module_bindings" in statement.lower() for statement in statements)


def test_validate_session_is_read_only_and_does_not_touch_last_seen(
    clean_auth_tables: None,
    test_settings,
) -> None:
    del clean_auth_tables
    owner_id = create_test_owner()
    raw_session_id = create_service_session(test_settings)
    session_hash = hash_session_id(raw_session_id)

    with SessionLocal() as db:
        auth_session = db.scalar(
            select(AuthSession).where(AuthSession.session_id_hash == session_hash)
        )
        assert auth_session is not None
        original_last_seen_at = auth_session.last_seen_at

    statements: list[str] = []

    def collect_statement(
        conn,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:
        del conn, cursor, parameters, context, executemany
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", collect_statement)
    try:
        with SessionLocal() as db:
            current_session = validate_session(
                db,
                session_id=raw_session_id,
                audit=service_audit_context("test-read-only-session-validation"),
            )
            assert current_session.user.id == owner_id
            db.rollback()
    finally:
        event.remove(engine, "before_cursor_execute", collect_statement)

    write_statements = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]
    assert write_statements == []

    with SessionLocal() as db:
        auth_session = db.scalar(
            select(AuthSession).where(AuthSession.session_id_hash == session_hash)
        )
        assert auth_session is not None
        assert auth_session.last_seen_at == original_last_seen_at


def test_session_last_seen_is_deferred_until_batch_flush(
    clean_auth_tables: None,
    test_settings,
) -> None:
    del clean_auth_tables
    create_test_owner()
    raw_session_id = create_service_session(test_settings)
    session_hash = hash_session_id(raw_session_id)
    clear_session_seen_buffer()

    with SessionLocal() as db:
        auth_session = db.scalar(
            select(AuthSession).where(AuthSession.session_id_hash == session_hash)
        )
        assert auth_session is not None
        original_last_seen_at = auth_session.last_seen_at

    deferred_seen_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    assert queue_session_seen(session_hash, seen_at=deferred_seen_at) is True

    with SessionLocal() as db:
        auth_session = db.scalar(
            select(AuthSession).where(AuthSession.session_id_hash == session_hash)
        )
        assert auth_session is not None
        assert auth_session.last_seen_at == original_last_seen_at

    assert flush_session_seen_updates(force=True) == 1

    with SessionLocal() as db:
        auth_session = db.scalar(
            select(AuthSession).where(AuthSession.session_id_hash == session_hash)
        )
        assert auth_session is not None
        assert aware(auth_session.last_seen_at) == deferred_seen_at


def test_auth_me_allows_active_non_owner_user(
    auth_client: TestClient,
) -> None:
    user_id = create_test_user(role="viewer")
    login_response = auth_client.post(
        "/api/public/auth/login",
        json={"username": OPERATOR_USERNAME, "password": OPERATOR_PASSWORD},
    )
    assert login_response.status_code == 200

    response = auth_client.get("/api/public/auth/me")

    assert response.status_code == 200
    assert response.json()["id"] == user_id
    assert response.json()["role"] == "viewer"
    assert "permissions" not in response.json()
    assert "password_hash" not in response.json()


def test_auth_context_is_lazy_org_context_endpoint(
    auth_client: TestClient,
) -> None:
    owner_id = create_test_owner()
    login(auth_client)

    response = auth_client.get("/api/public/auth/context")

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == owner_id
    assert payload["context_available"] is False
    assert payload["org_id"] is None
    assert payload["module_scope"] == []


def test_logout_invalidates_session_and_writes_audit_log(
    auth_client: TestClient,
) -> None:
    owner_id = create_test_owner()
    login_response = login(auth_client)
    raw_session_id = session_cookie(login_response)

    response = auth_client.post("/api/public/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"message": "Logged out."}

    with SessionLocal() as db:
        auth_session = db.scalar(
            select(AuthSession).where(
                AuthSession.session_id_hash == hash_session_id(raw_session_id)
            )
        )
        operation_log = db.scalar(
            select(OperationLog).where(
                OperationLog.action == "auth.logout"
            )
        )

    assert auth_session is not None
    assert auth_session.invalidated_at is not None
    assert auth_session.invalidation_reason == "logout"
    assert operation_log is not None
    assert operation_log.actor_id == str(owner_id)
    assert operation_log.result == "success"

    auth_client.cookies.clear()
    invalidated_response = auth_client.get(
        "/api/public/auth/me",
        headers={"Cookie": f"barong_ops_session={raw_session_id}"},
    )
    assert invalidated_response.status_code == 401


def test_auth_register_does_not_exist(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/public/auth/register",
        json={"username": "blocked", "password": "not-used"},
    )

    assert response.status_code == 404
