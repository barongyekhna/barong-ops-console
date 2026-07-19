from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from backend.app.core.config import Settings
from backend.app.modules.cs_series import reply_service


pytestmark = pytest.mark.unit

RELAY_URL = "https://barongyekhna.com/wp-json/barong-cs/v1/send"
SHARED_KEY = "unit-test-cs-shared-key"


def _settings() -> Settings:
    return Settings(
        cs_wp_send_url=RELAY_URL,
        cs_inbound_key=SecretStr(SHARED_KEY),
    )


class _StubClient:
    def __init__(
        self,
        behavior: Callable[..., httpx.Response],
        captured: dict[str, Any],
        **client_kwargs: object,
    ) -> None:
        self._behavior = behavior
        self._captured = captured
        captured["client_kwargs"] = client_kwargs
        captured["post_calls"] = []

    def __enter__(self) -> _StubClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        self._captured["post_calls"].append((url, kwargs))
        return self._behavior(url, **kwargs)


def _install_stub_client(
    monkeypatch: pytest.MonkeyPatch,
    behavior: Callable[..., httpx.Response],
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def client_factory(**kwargs: object) -> _StubClient:
        return _StubClient(behavior, captured, **kwargs)

    monkeypatch.setattr(reply_service.httpx, "Client", client_factory)
    return captured


def _target(channel: str = "retail") -> reply_service.CSReplyTarget:
    return reply_service.CSReplyTarget(
        email="alice@example.com",
        name="Alice Customer",
        channel=channel,
    )


def test_send_reply_uses_exact_wp_contract_and_single_fifteen_second_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def succeed(_url: str, **_kwargs: object) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    captured = _install_stub_client(monkeypatch, succeed)

    reply_service.send_cs_reply_to_wp(
        settings=_settings(),
        message=_target(),
        body="Hello Alice\nYour order is ready.",
    )

    client_kwargs = captured["client_kwargs"]
    timeout = client_kwargs["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == reply_service.CS_REPLY_TIMEOUT_SECONDS
    assert timeout.read == reply_service.CS_REPLY_TIMEOUT_SECONDS
    assert timeout.write == reply_service.CS_REPLY_TIMEOUT_SECONDS
    assert timeout.pool == reply_service.CS_REPLY_TIMEOUT_SECONDS
    assert client_kwargs["follow_redirects"] is False
    assert client_kwargs["trust_env"] is False

    assert len(captured["post_calls"]) == 1
    url, request_kwargs = captured["post_calls"][0]
    assert url == RELAY_URL
    assert request_kwargs["headers"] == {
        "Content-Type": "application/json",
        "X-BY-CS-KEY": SHARED_KEY,
    }
    assert request_kwargs["json"] == {
        "to_email": "alice@example.com",
        "to_name": "Alice Customer",
        "subject": "Re: Your message to Barong Yekhna",
        "body_text": "Hello Alice\nYour order is ready.",
        "channel": "retail",
    }


def test_wholesale_reply_uses_wholesale_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def succeed(_url: str, **_kwargs: object) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    captured = _install_stub_client(monkeypatch, succeed)

    reply_service.send_cs_reply_to_wp(
        settings=_settings(),
        message=_target(channel="wholesale"),
        body="Wholesale response",
    )

    _url, request_kwargs = captured["post_calls"][0]
    assert request_kwargs["json"]["subject"] == (
        "Re: Your wholesale inquiry — Barong Yekhna"
    )


def test_wp_500_maps_to_readable_delivery_error_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_with_500(_url: str, **_kwargs: object) -> httpx.Response:
        return httpx.Response(500, json={"ok": False})

    captured = _install_stub_client(monkeypatch, fail_with_500)

    with pytest.raises(reply_service.CSReplyDeliveryError) as exc_info:
        reply_service.send_cs_reply_to_wp(
            settings=_settings(),
            message=_target(),
            body="One attempt only",
        )

    assert exc_info.value.provider_note == (
        "WordPress reply relay returned HTTP 500."
    )
    assert len(captured["post_calls"]) == 1


def test_wp_2xx_with_ok_false_is_rejected_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(_url: str, **_kwargs: object) -> httpx.Response:
        return httpx.Response(200, json={"ok": False})

    captured = _install_stub_client(monkeypatch, reject)

    with pytest.raises(reply_service.CSReplyDeliveryError) as exc_info:
        reply_service.send_cs_reply_to_wp(
            settings=_settings(),
            message=_target(),
            body="One attempt only",
        )

    assert exc_info.value.provider_note == (
        "WordPress reply relay rejected the reply."
    )
    assert len(captured["post_calls"]) == 1


def test_wp_timeout_maps_to_readable_delivery_error_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def time_out(url: str, **_kwargs: object) -> httpx.Response:
        raise httpx.ReadTimeout(
            "simulated timeout",
            request=httpx.Request("POST", url),
        )

    captured = _install_stub_client(monkeypatch, time_out)

    with pytest.raises(reply_service.CSReplyDeliveryError) as exc_info:
        reply_service.send_cs_reply_to_wp(
            settings=_settings(),
            message=_target(),
            body="One attempt only",
        )

    assert exc_info.value.provider_note == (
        "WordPress reply relay timed out after 15 seconds."
    )
    assert len(captured["post_calls"]) == 1
