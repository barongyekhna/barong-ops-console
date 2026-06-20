from types import SimpleNamespace

from sqlalchemy import event

from backend.app.core.permissions import SCOPE_GLOBAL
from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal, engine as db_engine
from backend.app.models.user import User
from backend.app.services.permission_decision_engine import PermissionDecisionEngine
from backend.app.services.permission_resolution_cache import (
    clear_permission_ttl_cache,
    get_permission_request_cache,
)
from backend.app.services.permission_service import (
    grant_permission,
    upsert_permission_registry,
)
from backend.app.services.unified_permission_engine import UnifiedPermissionRequest


class DummyRequest:
    def __init__(self) -> None:
        self.state = SimpleNamespace()


def _create_user(*, username: str, role: str) -> int:
    with SessionLocal() as db:
        user = User(
            username=username,
            password_hash=hash_password("permission-cache-test-password"),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return user.id


def test_permission_decision_engine_deduplicates_request_and_ttl_queries(
    clean_auth_tables: None,
) -> None:
    clear_permission_ttl_cache()
    user_id = _create_user(username="permission_cache_operator", role="operator")
    with SessionLocal() as db:
        upsert_permission_registry(db)
        grant_permission(
            db,
            user_id=user_id,
            permission_key="artifacts.read",
            reason="permission cache test",
        )

    statements: list[str] = []

    def record_query(*args: object) -> None:
        statement = str(args[2])
        if "permission" in statement or "users" in statement:
            statements.append(statement)

    event.listen(db_engine, "before_cursor_execute", record_query)
    try:
        with SessionLocal() as db:
            request = DummyRequest()
            permission_request = UnifiedPermissionRequest(
                user_id=user_id,
                org_id=None,
                module_id="artifacts",
                action="read",
                role="operator",
                scope_type=SCOPE_GLOBAL,
                scope_key="*",
                permission_key="artifacts.read",
                source="test_permission_decision_cache",
            )
            permission_engine = PermissionDecisionEngine(db, request=request)

            first = permission_engine.decide_permission_key(permission_request)
            queries_after_first = len(statements)
            second = permission_engine.decide_permission_key(permission_request)
            queries_after_second = len(statements)

            assert first.allowed is True
            assert second is first
            assert queries_after_first > 0
            assert queries_after_second == queries_after_first

            cache = get_permission_request_cache(request)
            assert cache is not None
            assert cache.decision_evaluations == 1
            assert cache.decision_hits == 1

        with SessionLocal() as db:
            request = DummyRequest()
            permission_engine = PermissionDecisionEngine(db, request=request)
            third = permission_engine.decide_permission_key(permission_request)

            assert third.allowed is True
            assert len(statements) == queries_after_second

            cache = get_permission_request_cache(request)
            assert cache is not None
            assert cache.decision_evaluations == 1
            assert cache.ttl_material_hits > 0
    finally:
        event.remove(db_engine, "before_cursor_execute", record_query)
        clear_permission_ttl_cache()
