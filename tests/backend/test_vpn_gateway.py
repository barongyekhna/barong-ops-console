from __future__ import annotations

import unittest

from backend.vpn_gateway import (
    AUTH_URL,
    VPN_AGENT_STATUS_URL,
    GatewayError,
    UpstreamUnavailable,
    dependency_health,
    get_authenticated_vpn_status,
    sanitize_vpn_status,
)


def agent_payload() -> dict[str, object]:
    return {
        "status": "ok",
        "generated_at": "2026-07-15T00:00:00Z",
        "agent_version": "0.1.0",
        "private_key": "must-never-leak",
        "vpn": {
            "interface": "awg0",
            "service": {
                "active_state": "active",
                "sub_state": "exited",
                "active_since": "Tue 2026-07-14 12:45:01 UTC",
                "unit_secrets": "must-never-leak",
            },
            "address": "10.66.66.1/24",
            "listen_port": 443,
            "expected_listen_port": 443,
            "peer_count": 0,
            "recently_active_peer_count": 0,
            "latest_handshake_at": None,
            "transfer": {
                "received_bytes": 0,
                "sent_bytes": 0,
                "peer_public_keys": ["must-never-leak"],
            },
            "peers": [{"public_key": "must-never-leak"}],
        },
        "warnings": [],
    }


class VpnGatewayTests(unittest.TestCase):
    def test_status_requires_a_cookie_without_calling_upstreams(self) -> None:
        calls: list[str] = []

        def fake_fetcher(url: str, _headers, _timeout: float):
            calls.append(url)
            return 200, {}

        with self.assertRaises(GatewayError) as context:
            get_authenticated_vpn_status(None, fetcher=fake_fetcher)
        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(calls, [])

    def test_all_authenticated_users_can_read_without_org_or_role_checks(self) -> None:
        calls: list[tuple[str, dict[str, str]]] = []

        def fake_fetcher(url: str, headers, _timeout: float):
            calls.append((url, dict(headers)))
            if url == AUTH_URL:
                return 200, {"id": "user_any", "role": "ordinary_user"}
            if url == VPN_AGENT_STATUS_URL:
                return 200, agent_payload()
            raise AssertionError(url)

        payload = get_authenticated_vpn_status(
            "barong_session=opaque-value",
            fetcher=fake_fetcher,
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(calls[0][1], {"Cookie": "barong_session=opaque-value"})
        self.assertEqual(calls[1][1], {})

    def test_invalid_session_is_rejected(self) -> None:
        def fake_fetcher(url: str, _headers, _timeout: float):
            if url == AUTH_URL:
                return 401, None
            raise AssertionError("VPN agent must not be called")

        with self.assertRaises(GatewayError) as context:
            get_authenticated_vpn_status("invalid=1", fetcher=fake_fetcher)
        self.assertEqual(context.exception.status_code, 401)

    def test_agent_output_is_allowlisted(self) -> None:
        payload = sanitize_vpn_status(agent_payload())
        serialized = repr(payload)
        self.assertNotIn("private_key", serialized)
        self.assertNotIn("public_key", serialized)
        self.assertNotIn("peers", serialized)
        self.assertNotIn("unit_secrets", serialized)
        self.assertEqual(payload["vpn"]["interface"], "awg0")

    def test_agent_outage_returns_generic_unavailable_error(self) -> None:
        def fake_fetcher(url: str, _headers, _timeout: float):
            if url == AUTH_URL:
                return 200, {"id": "user_any"}
            raise UpstreamUnavailable

        with self.assertRaises(GatewayError) as context:
            get_authenticated_vpn_status("session=opaque", fetcher=fake_fetcher)
        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(context.exception.detail, "VPN status temporarily unavailable.")

    def test_health_reports_only_dependency_availability(self) -> None:
        def fake_fetcher(_url: str, _headers, _timeout: float):
            return 200, {"status": "ok", "secret": "not-forwarded"}

        status_code, payload = dependency_health(fetcher=fake_fetcher)
        self.assertEqual(status_code, 200)
        self.assertEqual(
            payload["dependencies"],
            {"console_backend": "ok", "vpn_agent": "ok"},
        )
        self.assertNotIn("secret", repr(payload))


if __name__ == "__main__":
    unittest.main()
