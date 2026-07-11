from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from c19_record_service.app import create_app
from c19_record_service.auth import require_service_token
from c19_record_service.config import (
    RecordServiceConfigurationError,
    RecordServiceSettings,
)

from helpers import CURSOR_SECRET, SERVICE_TOKEN


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
        "/v1/conversations/{conversation_id}/delivery",
        "/v1/conversations/{conversation_id}/read",
        "/v1/conversations/{conversation_id}/unread",
        "/v1/conversations/{conversation_id}/resume",
        "/v1/users/{user_id}/events",
        "/v1/users/{user_id}/events/tail",
        "/v1/records/delete",
        "/v1/retention/apply",
    } <= route_paths

    asyncio.run(require_service_token(_request(app, SERVICE_TOKEN)))
    for token in (None, "wrong-token"):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(require_service_token(_request(app, token)))
        assert raised.value.status_code == 401

    app.state.database.dispose()


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
