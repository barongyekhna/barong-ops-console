import json
import logging

import httpx

from backend.app.modules.key_health.worker_main import _configure_logging
from backend.app.modules.key_health.probes import (
    ProbeTarget,
    adapter_for_target,
    probe_target,
    safe_probe_target,
)


def test_worker_suppresses_request_urls_from_http_client_logs() -> None:
    _configure_logging()

    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() == logging.WARNING


def _target(
    *,
    url: str,
    key_type: str = "custom",
    aliases: tuple[str, ...] = (),
    secret: str = "test-secret-value",
) -> ProbeTarget:
    return ProbeTarget(
        key_id="key_00000000000000000000000000000000",
        org_id="org_00000000000000000000000000000000",
        name="test key",
        url=url,
        key_hash_prefix="abcdef123456",
        key_type=key_type,
        aliases=aliases,
        secret_value=secret,
    )


def test_claude_and_chatgpt_probes_stay_on_existing_4sapi_proxy() -> None:
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        assert request.url.scheme == "https"
        assert request.url.host == "4sapi.com"
        assert request.url.path == "/v1/models"
        assert request.headers["authorization"] == "Bearer test-secret-value"
        return httpx.Response(200, json={"data": [{"id": "proxy-model"}]})

    transport = httpx.MockTransport(handler)
    for alias in ("chatgpt", "claude_opus"):
        target = _target(url="http://4sapi.com", aliases=(alias,))
        assert adapter_for_target(target) == "4sapi_openai_compatible"
        result = probe_target(
            target,
            enforce_public_network=False,
            transport=transport,
        )
        assert result.status == "healthy"
        assert result.reason_code == "models_list_ok"

    assert len(requested) == 2


def test_claude_probe_refuses_non_4sapi_route_without_network_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected outbound request: {request.url}")

    target = _target(
        url="https://api.anthropic.com",
        key_type="claude_opus",
        aliases=("claude_opus",),
    )
    result = probe_target(
        target,
        enforce_public_network=False,
        transport=httpx.MockTransport(handler),
    )
    assert result.status == "malformed"
    assert result.reason_code == "required_4sapi_proxy_route_missing"


def test_google_ads_oauth_success_and_basic_review_is_warning() -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(str(request.url.host))
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ephemeral-token"})
        assert request.url.host == "googleads.googleapis.com"
        assert request.url.path.startswith("/v24/customers/")
        return httpx.Response(
            403,
            json={
                "error": {
                    "details": [
                        {"errors": [{"errorCode": {"authorizationError": "DEVELOPER_TOKEN_NOT_APPROVED"}}]}
                    ]
                }
            },
        )

    secret = json.dumps(
        {
            "developer_token": "developer-token",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "refresh_token": "refresh-token",
            "customer_id": "123-456-7890",
        }
    )
    result = probe_target(
        _target(url="https://googleads.googleapis.com", key_type="google_ads", secret=secret),
        enforce_public_network=False,
        transport=httpx.MockTransport(handler),
    )
    assert result.status == "pending_review"
    assert result.reason_code == "basic_access_review_pending"
    assert requested_hosts == ["oauth2.googleapis.com", "googleads.googleapis.com"]
    assert "ephemeral-token" not in repr(result)


def test_1688_non_consuming_probe_validates_payload_and_gateway() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://gw.open.1688.com")
        assert "authorization" not in request.headers
        return httpx.Response(404)

    secret = json.dumps(
        {
            "app_key": "app-key",
            "app_secret": "app-secret",
            "access_token": "access-token",
            "expires_at": "2099-01-01T00:00:00Z",
        }
    )
    result = probe_target(
        _target(url="https://gw.open.1688.com", key_type="alibaba1688", secret=secret),
        enforce_public_network=False,
        transport=httpx.MockTransport(handler),
    )
    assert result.status == "healthy"
    assert result.reason_code == "credential_structure_and_gateway_ok"
    assert result.details["check_depth"] == "non_consuming"


def test_provider_alias_cannot_redirect_secret_to_another_host() -> None:
    target = _target(url="https://127.0.0.1", aliases=("deepseek",))
    result = safe_probe_target(target)
    assert result.status == "malformed"
    assert result.reason_code == "provider_host_mismatch"


def test_wordpress_probe_authenticates_via_users_me() -> None:
    secret = json.dumps(
        {
            "base_url": "https://barongyekhna.com",
            "user": "barongyekhna",
            "app_password": "abcd efgh ijkl mnop qrst uvwx",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "barongyekhna.com"
        assert request.url.path == "/wp-json/wp/v2/users/me"
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(200, json={"id": 1, "name": "barongyekhna"})

    target = _target(
        url="https://barongyekhna.com",
        aliases=("wordpress",),
        secret=secret,
    )
    assert adapter_for_target(target) == "wordpress"
    result = probe_target(
        target,
        enforce_public_network=False,
        transport=httpx.MockTransport(handler),
    )
    assert result.status == "healthy"
    assert result.reason_code == "wp_auth_ok"


def test_wordpress_probe_flags_bad_secret_and_bad_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "invalid_username"})

    # 非 JSON 密钥值 → malformed,不出网
    target = _target(url="https://barongyekhna.com", aliases=("wordpress",), secret="not-json")
    result = probe_target(target, enforce_public_network=False, transport=None)
    assert result.status == "malformed"
    assert result.reason_code == "wordpress_secret_not_json"

    # 认证被拒 → invalid
    secret = json.dumps(
        {
            "base_url": "https://barongyekhna.com",
            "user": "barongyekhna",
            "app_password": "wrong",
        }
    )
    target = _target(url="https://barongyekhna.com", aliases=("wordpress",), secret=secret)
    result = probe_target(
        target,
        enforce_public_network=False,
        transport=httpx.MockTransport(handler),
    )
    assert result.status == "invalid"
    assert result.reason_code == "authentication_rejected"


def test_serper_credits_exhausted_maps_to_actionable_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "Not enough credits", "statusCode": 400})

    target = _target(url="https://google.serper.dev", aliases=("serper",))
    result = probe_target(
        target,
        enforce_public_network=False,
        transport=httpx.MockTransport(handler),
    )
    assert result.status == "provider_error"
    assert result.reason_code == "provider_credits_exhausted"


def test_track17_probe_reads_body_code_semantics() -> None:
    def ok_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.17track.net"
        assert request.url.path == "/track/v2.2/getquota"
        assert request.headers["17token"] == "test-secret-value"
        return httpx.Response(200, json={"code": 0, "data": {"quota_total": 100}})

    target = _target(url="https://api.17track.net", key_type="track17")
    assert adapter_for_target(target) == "track17"
    result = probe_target(
        target,
        enforce_public_network=False,
        transport=httpx.MockTransport(ok_handler),
    )
    assert result.status == "healthy"
    assert result.reason_code == "quota_ok"

    # 17TRACK 鉴权失败也回 HTTP 200,错误码在 body(-1801xxxx 段)
    def bad_key_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": -18010002, "data": None})

    result = probe_target(
        target,
        enforce_public_network=False,
        transport=httpx.MockTransport(bad_key_handler),
    )
    assert result.status == "invalid"
    assert result.reason_code == "authentication_rejected"

    # 其它业务错误码(如额度类)→ provider_error,不误判为密钥失效
    def other_error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": -18019902, "data": None})

    result = probe_target(
        target,
        enforce_public_network=False,
        transport=httpx.MockTransport(other_error_handler),
    )
    assert result.status == "provider_error"
    assert result.reason_code == "track17_code_-18019902"
