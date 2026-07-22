"""Unit contracts for the H WordPress bridge and redirect safety rails."""

from __future__ import annotations

import inspect
from urllib.parse import urlsplit

import pytest
from pydantic import ValidationError

from backend.app.modules.h_series.sitehealth import router
from backend.app.services import wp_bridge
from r_system_v2.core.secret_manager import (
    H_SITE_HEALTH_MODULE_ID,
    SERVICE_BINDING_CANDIDATES,
)


pytestmark = pytest.mark.unit


def _env_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WP_BASE_URL", "https://barongyekhna.com")
    monkeypatch.setenv("WP_APP_USER", "wp-bridge-test")
    monkeypatch.setenv("WP_APP_PASSWORD", "app-password-test")


def test_wordpress_binding_is_scoped_to_h_site_health() -> None:
    assert SERVICE_BINDING_CANDIDATES["wordpress"] == (
        (H_SITE_HEALTH_MODULE_ID, "wordpress"),
    )


def test_option_allowlist_rejects_reads_and_writes_before_network_access() -> None:
    with pytest.raises(ValueError, match="wordpress_option_not_allowed"):
        wp_bridge.get_option("siteurl")
    with pytest.raises(ValueError, match="wordpress_option_not_allowed"):
        wp_bridge.set_option("users_can_register", True)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"rules": [{"from": "old", "to": "/new"}]}, "旧路径"),
        ({"rules": [{"from": "/old", "to": "https://evil.example/new"}]}, "新目标"),
        ({"rules": [{"from": "/old", "to": "//evil.example/new"}]}, "站外跳转"),
        ({"rules": [{"from": "/old", "to": "http://barongyekhna.com/new"}]}, "新目标"),
        ({"rules": [{"from": "/" + ("x" * 500), "to": "/new"}]}, "500"),
    ],
)
def test_redirect_validation_matrix(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        router.RedirectRulesRequest.model_validate(payload)


def test_redirect_rules_trim_and_last_duplicate_wins() -> None:
    payload = router.RedirectRulesRequest.model_validate(
        {
            "rules": [
                {"from": " /old ", "to": " /first "},
                {"from": "/keep", "to": "https://barongyekhna.com/new"},
                {"from": "/old", "to": "/last"},
            ]
        }
    )
    assert router._normalized_redirect_rules(payload.rules) == [
        {"from": "/keep", "to": "https://barongyekhna.com/new"},
        {"from": "/old", "to": "/last"},
    ]


def test_redirect_rule_count_is_capped_at_200() -> None:
    with pytest.raises(ValidationError):
        router.RedirectRulesRequest.model_validate(
            {
                "rules": [
                    {"from": f"/old-{index}", "to": "/new"}
                    for index in range(201)
                ]
            }
        )


def test_corrupt_redirect_option_degrades_to_empty_table() -> None:
    rules, parse_error = router._redirect_rules_from_option("{not-json")
    assert rules == []
    assert parse_error


def test_verify_path_requires_a_relative_site_path_and_forbids_host_field() -> None:
    with pytest.raises(ValidationError):
        router.RedirectVerifyRequest.model_validate(
            {"path": "https://evil.example/steal"}
        )
    with pytest.raises(ValidationError):
        router.RedirectVerifyRequest.model_validate(
            {"path": "/safe", "host": "evil.example"}
        )


def test_verify_always_uses_configured_wordpress_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env_credentials(monkeypatch)
    captured: dict[str, str] = {}

    class FakeResponse:
        status = 200
        headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):  # noqa: ANN002
            return False

    class FakeOpener:
        def open(self, request, timeout):  # noqa: ANN001
            del timeout
            captured["url"] = request.full_url
            return FakeResponse()

    monkeypatch.setattr(wp_bridge.urllib.request, "build_opener", lambda *args: FakeOpener())
    result = wp_bridge.verify_redirect("//evil.example/steal")

    assert result == {"status": 200, "location": None}
    assert urlsplit(captured["url"]).hostname == "barongyekhna.com"


def test_wordpress_unreachable_has_stable_degraded_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env_credentials(monkeypatch)
    monkeypatch.setattr(
        wp_bridge,
        "_request_json",
        lambda *args, **kwargs: {"reachable": False, "error": "wordpress_unreachable"},
    )
    assert wp_bridge.get_option("barong_redirect_map") == {
        "reachable": False,
        "error": "wordpress_unreachable",
        "value": None,
    }
    assert wp_bridge.fetch_plugins() == {
        "reachable": False,
        "error": "wordpress_unreachable",
        "plugins": [],
    }


def test_sentinel_endpoint_never_triggers_smtp_diagnostic() -> None:
    source = inspect.getsource(router.h_wp_sentinel)
    assert "smtp" not in source.lower()
    assert "smtpdiag" not in source.lower()


def test_smtp_check_only_returns_non_secret_diagnostic_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env_credentials(monkeypatch)
    monkeypatch.setenv("CS_INBOUND_KEY", "shared-diagnostic-key")
    monkeypatch.setattr(
        wp_bridge,
        "_request_json",
        lambda *args, **kwargs: {
            "reachable": True,
            "data": {
                "probe": "smtp-login",
                "verdict_line": "ok",
                "host": "smtp.example.test",
                "username": "mailer@example.test",
                "password_masked": "do-not-forward",
            },
        },
    )

    result = wp_bridge.smtp_check()

    assert result == {
        "reachable": True,
        "probe": "smtp-login",
        "verdict_line": "ok",
        "host": "smtp.example.test",
        "username": "mailer@example.test",
    }
    assert "password_masked" not in result
