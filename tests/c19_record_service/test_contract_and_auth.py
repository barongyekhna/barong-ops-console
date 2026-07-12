from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from c19_record_service.app import create_app
from c19_record_service.auth import require_service_token
from c19_record_service.config import (
    RecordServiceConfigurationError,
    RecordServiceSettings,
)
from c19_record_service.repository import append_record
from c19_record_service.schemas import UnreadSummaryRequest

from helpers import CURSOR_SECRET, SERVICE_TOKEN, make_asset, make_record


def _request(app, token: str | None) -> Request:
    headers = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/users/u/events",
            "query_string": b"",
            "headers": headers,
            "app": app,
        }
    )


def test_every_v1_route_is_service_authenticated_and_health_is_public(settings) -> None:
    app = create_app(settings, create_schema=True)
    route_paths = {route.path for route in app.routes}
    assert "/healthz" in route_paths
    assert {
        "/v1/records",
        "/v1/conversations/{conversation_id}/records",
        "/v1/conversations/{conversation_id}/records/{record_id}",
        "/v1/conversations/{conversation_id}/delivery",
        "/v1/conversations/{conversation_id}/read",
        "/v1/conversations/{conversation_id}/unread",
        "/v1/users/{user_id}/unread-summary",
        "/v1/conversations/{conversation_id}/resume",
        "/v1/users/{user_id}/events",
        "/v1/users/{user_id}/events/tail",
        "/v1/records/delete",
        "/v1/retention/apply",
        "/v1/ops/snapshot",
        "/v1/moments/drafts",
        "/v1/moments/{moment_id}/draft/query",
        "/v1/moments/{moment_id}/publish",
        "/v1/moments/feed/query",
        "/v1/moments/{moment_id}/query",
        "/v1/moments/{moment_id}/likes",
        "/v1/moments/{moment_id}/likes/remove",
        "/v1/moments/{moment_id}/likes/query",
        "/v1/moments/{moment_id}/comments",
        "/v1/moments/{moment_id}/comments/query",
        "/v1/moments/{moment_id}/comments/{comment_id}/delete",
        "/v1/moments/{moment_id}/delete",
        "/v1/moments/{moment_id}/delete/complete",
        "/v1/moments/events/query",
        "/v1/moments/events/tail",
    } <= route_paths

    asyncio.run(require_service_token(_request(app, SERVICE_TOKEN)))
    for token in (None, "wrong-token"):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(require_service_token(_request(app, token)))
        assert raised.value.status_code == 401

    app.state.database.dispose()


def test_unread_summary_contract_is_strict_unique_and_bounded() -> None:
    assert UnreadSummaryRequest(conversation_ids=[]).conversation_ids == []
    assert UnreadSummaryRequest(
        conversation_ids=["conversation-1", "conversation-2"]
    ).conversation_ids == ["conversation-1", "conversation-2"]
    with pytest.raises(ValidationError):
        UnreadSummaryRequest(
            conversation_ids=["conversation-1", "conversation-1"]
        )
    with pytest.raises(ValidationError):
        UnreadSummaryRequest(conversation_ids=[f"conversation-{i}" for i in range(1001)])
    with pytest.raises(ValidationError):
        UnreadSummaryRequest.model_validate(
            {"conversation_ids": [], "unexpected": "must-fail-closed"}
        )


def test_settings_require_independent_long_secrets() -> None:
    with pytest.raises(RecordServiceConfigurationError):
        RecordServiceSettings(
            database_url="sqlite://",
            service_token="short",
            cursor_signing_secret=CURSOR_SECRET,
        )
    with pytest.raises(RecordServiceConfigurationError):
        RecordServiceSettings(
            database_url="sqlite://",
            service_token=SERVICE_TOKEN,
            cursor_signing_secret="short",
        )


@pytest.mark.parametrize(
    ("database_url", "service_token", "cursor_secret"),
    (
        (
            "postgresql+psycopg://user:CHANGE-ME@db/records",
            SERVICE_TOKEN,
            CURSOR_SECRET,
        ),
        (
            "sqlite://",
            "change-me-service-token-" + "x" * 32,
            CURSOR_SECRET,
        ),
        (
            "sqlite://",
            SERVICE_TOKEN,
            "prefix-ChAnGe-Me-cursor-secret-" + "y" * 32,
        ),
    ),
)
def test_settings_reject_change_me_placeholders(
    database_url: str, service_token: str, cursor_secret: str
) -> None:
    with pytest.raises(RecordServiceConfigurationError):
        RecordServiceSettings(
            database_url=database_url,
            service_token=service_token,
            cursor_signing_secret=cursor_secret,
        )


def test_database_errors_hide_bound_message_content_and_return_sanitized_500(
    settings, caplog
) -> None:
    app = create_app(settings, create_schema=True)
    secret_body = "highly-sensitive-chat-body"
    assert app.state.database.engine.hide_parameters is True

    with app.state.database.session_factory() as session:
        with pytest.raises(SQLAlchemyError) as raised:
            session.execute(
                text(
                    "insert into table_that_does_not_exist(content) "
                    "values (:content)"
                ),
                {"content": secret_body},
            )
    assert secret_body not in str(raised.value)
    assert secret_body not in repr(raised.value)
    assert "parameters hidden" in str(raised.value).lower()

    handler = app.exception_handlers[SQLAlchemyError]
    response = asyncio.run(handler(_request(app, SERVICE_TOKEN), raised.value))
    assert response.status_code == 500
    assert secret_body.encode() not in response.body
    assert secret_body not in caplog.text
    app.state.database.dispose()


def test_validation_errors_never_reflect_private_content(settings) -> None:
    app = create_app(settings, create_schema=True)
    secret_body = "private-moment-body-must-not-be-reflected"
    error = RequestValidationError(
        [
            {
                "type": "string_too_long",
                "loc": ("body", "content"),
                "msg": "String should have at most 4000 characters",
                "input": secret_body,
            }
        ]
    )
    handler = app.exception_handlers[RequestValidationError]
    response = asyncio.run(handler(_request(app, SERVICE_TOKEN), error))
    assert response.status_code == 422
    assert secret_body.encode() not in response.body
    assert response.body == (
        b'{"detail":"record service request validation failed"}'
    )
    app.state.database.dispose()


def test_exact_visibility_route_returns_typed_refs_and_uniform_404(settings) -> None:
    app = create_app(settings, create_schema=True)
    body = make_record(
        1,
        content="",
        content_type="image",
        assets=[make_asset(1)],
    )
    exact_route = next(
        route
        for route in app.routes
        if route.path
        == "/v1/conversations/{conversation_id}/records/{record_id}"
    )
    with app.state.database.session_factory() as session:
        record_id = append_record(
            session, body, max_message_chars=1000
        ).record.record_id
    with app.state.database.session_factory() as session:
        visible = exact_route.endpoint(
            conversation_id="conversation-1",
            record_id=record_id,
            user_id="user-2",
            session=session,
        )
        assert visible.assets == body.assets
        serialized = visible.model_dump_json().lower()
        assert "object_key" not in serialized
        assert "download_url" not in serialized
        assert "locator" not in serialized

    missing_cases = (
        ("conversation-1", record_id, "user-3"),
        ("wrong", record_id, "user-2"),
        ("conversation-1", "missing", "user-2"),
    )
    for conversation_id, missing_record_id, user_id in missing_cases:
        with app.state.database.session_factory() as session:
            with pytest.raises(HTTPException) as raised:
                exact_route.endpoint(
                    conversation_id=conversation_id,
                    record_id=missing_record_id,
                    user_id=user_id,
                    session=session,
                )
            assert raised.value.status_code == 404
            assert raised.value.detail == "record not found"
    app.state.database.dispose()
