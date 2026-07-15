from __future__ import annotations

import unittest

from backend.vpn_gateway import (
    AUTH_URL,
    VPN_AGENT_DEVICES_URL,
    VPN_AGENT_STATUS_URL,
    GatewayError,
    UpstreamUnavailable,
    create_authenticated_device,
    dependency_health,
    get_authenticated_devices,
    get_authenticated_vpn_status,
    sanitize_created_device,
    sanitize_device_list,
    sanitize_vpn_status,
    update_authenticated_device,
)


DEVICE_ID = "2f6fcb65-b51f-4b29-bc65-85f71437c2ac"
AGENT_TOKEN = "agent-token-that-is-never-returned"


def agent_status_payload() -> dict[str, object]:
    return {
        "status": "ok",
        "generated_at": "2026-07-15T00:00:00Z",
        "agent_version": "0.2.0",
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
            "peer_count": 1,
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


def agent_device() -> dict[str, object]:
    return {
        "id": DEVICE_ID,
        "owner_id": "must-never-leak",
        "name": "办公电脑",
        "platform": "windows",
        "address": "10.66.66.2/32",
        "enabled": True,
        "created_at": "2026-07-15T01:00:00Z",
        "updated_at": "2026-07-15T01:00:00Z",
        "last_handshake_at": None,
        "received_bytes": 0,
        "sent_bytes": 0,
        "public_key": "must-never-leak",
        "preshared_key": "must-never-leak",
    }


class VpnGatewayTests(unittest.TestCase):
    def test_status_requires_a_cookie_without_calling_upstreams(self) -> None:
        calls: list[str] = []

        def fake_fetcher(url, _method, _headers, _payload, _timeout):
            calls.append(url)
            return 200, {}

        with self.assertRaises(GatewayError) as context:
            get_authenticated_vpn_status(None, fetcher=fake_fetcher)
        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(calls, [])

    def test_all_authenticated_users_can_read_status_without_role_checks(self) -> None:
        calls: list[tuple[str, str, dict[str, str]]] = []

        def fake_fetcher(url, method, headers, _payload, _timeout):
            calls.append((url, method, dict(headers)))
            if url == AUTH_URL:
                return 200, {"id": "user_any", "role": "ordinary_user"}
            if url == VPN_AGENT_STATUS_URL:
                return 200, agent_status_payload()
            raise AssertionError(url)

        payload = get_authenticated_vpn_status(
            "barong_session=opaque-value",
            fetcher=fake_fetcher,
        )
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(calls[0][2], {"Cookie": "barong_session=opaque-value"})
        self.assertEqual(calls[1][2], {})

    def test_device_list_is_scoped_to_authenticated_identity(self) -> None:
        calls: list[tuple[str, str, dict[str, str], object]] = []

        def fake_fetcher(url, method, headers, payload, _timeout):
            calls.append((url, method, dict(headers), payload))
            if url == AUTH_URL:
                return 200, {"id": "user-123", "organization_id": "ignored"}
            if url == VPN_AGENT_DEVICES_URL:
                return 200, {"devices": [agent_device()]}
            raise AssertionError(url)

        result = get_authenticated_devices(
            "session=opaque",
            agent_token=AGENT_TOKEN,
            fetcher=fake_fetcher,
        )
        self.assertEqual(len(result["devices"]), 1)
        agent_headers = calls[1][2]
        self.assertEqual(agent_headers["X-Barong-User-ID"], "user-123")
        self.assertEqual(agent_headers["Authorization"], f"Bearer {AGENT_TOKEN}")
        serialized = repr(result)
        self.assertNotIn("owner_id", serialized)
        self.assertNotIn("public_key", serialized)
        self.assertNotIn("preshared_key", serialized)
        self.assertNotIn(AGENT_TOKEN, serialized)

    def test_create_forwards_only_allowlisted_fields_and_returns_config_once(self) -> None:
        calls: list[tuple[str, str, dict[str, str], object]] = []

        def fake_fetcher(url, method, headers, payload, _timeout):
            calls.append((url, method, dict(headers), payload))
            if url == AUTH_URL:
                return 200, {"id": "user-123"}
            if url == VPN_AGENT_DEVICES_URL:
                return 201, {
                    "device": agent_device(),
                    "configuration": "[Interface]\nPrivateKey = one-time-only\n",
                    "one_time": True,
                    "unknown": "drop-me",
                }
            raise AssertionError(url)

        result = create_authenticated_device(
            "session=opaque",
            {"name": "  办公电脑  ", "platform": "windows", "owner_id": "attacker"},
            agent_token=AGENT_TOKEN,
            fetcher=fake_fetcher,
        )
        self.assertEqual(
            calls[1][3],
            {"name": "办公电脑", "platform": "windows"},
        )
        self.assertEqual(result["one_time"], True)
        self.assertIn("PrivateKey", result["configuration"])
        self.assertNotIn("unknown", result)

    def test_update_uses_authenticated_owner_and_boolean_only(self) -> None:
        calls: list[tuple[str, str, dict[str, str], object]] = []

        def fake_fetcher(url, method, headers, payload, _timeout):
            calls.append((url, method, dict(headers), payload))
            if url == AUTH_URL:
                return 200, {"id": "user-123"}
            return 200, {"device": {**agent_device(), "enabled": False}}

        result = update_authenticated_device(
            "session=opaque",
            DEVICE_ID,
            {"enabled": False, "owner_id": "attacker"},
            agent_token=AGENT_TOKEN,
            fetcher=fake_fetcher,
        )
        self.assertEqual(calls[1][1], "PATCH")
        self.assertEqual(calls[1][3], {"enabled": False})
        self.assertEqual(calls[1][2]["X-Barong-User-ID"], "user-123")
        self.assertFalse(result["device"]["enabled"])

    def test_invalid_session_never_reaches_the_agent(self) -> None:
        def fake_fetcher(url, _method, _headers, _payload, _timeout):
            if url == AUTH_URL:
                return 401, None
            raise AssertionError("VPN agent must not be called")

        with self.assertRaises(GatewayError) as context:
            get_authenticated_devices(
                "invalid=1",
                agent_token=AGENT_TOKEN,
                fetcher=fake_fetcher,
            )
        self.assertEqual(context.exception.status_code, 401)

    def test_agent_outputs_are_allowlisted(self) -> None:
        status = sanitize_vpn_status(agent_status_payload())
        devices = sanitize_device_list({"devices": [agent_device()]})
        created = sanitize_created_device(
            {
                "device": agent_device(),
                "configuration": "one-time-config",
                "one_time": True,
                "private_key": "drop-me",
            }
        )
        serialized = repr((status, devices, created))
        self.assertNotIn("public_key", serialized)
        self.assertNotIn("preshared_key", serialized)
        self.assertNotIn("owner_id", serialized)
        self.assertNotIn("drop-me", serialized)
        self.assertEqual(status["vpn"]["interface"], "awg0")

    def test_agent_outage_returns_generic_unavailable_error(self) -> None:
        def fake_fetcher(url, _method, _headers, _payload, _timeout):
            if url == AUTH_URL:
                return 200, {"id": "user_any"}
            raise UpstreamUnavailable

        with self.assertRaises(GatewayError) as context:
            get_authenticated_vpn_status("session=opaque", fetcher=fake_fetcher)
        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(context.exception.detail, "VPN status temporarily unavailable.")

    def test_health_reports_only_dependency_availability(self) -> None:
        def fake_fetcher(_url, _method, _headers, _payload, _timeout):
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
