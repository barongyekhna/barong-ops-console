from __future__ import annotations

import unittest

from backend.vpn_gateway import (
    AUTH_URL,
    LEGACY_NODES,
    Node,
    GatewayError,
    UpstreamUnavailable,
    dependency_health,
    enroll_authenticated_device,
    get_authenticated_devices,
    get_authenticated_nodes,
    get_authenticated_vpn_status,
    parse_nodes,
    sanitize_device_list,
    sanitize_node_info,
    sanitize_vpn_status,
    update_authenticated_device,
)


DEVICE_ID = "2f6fcb65-b51f-4b29-bc65-85f71437c2ac"
AGENT_TOKEN = "agent-token-that-is-never-returned"
PUBLIC_KEY = f"{'E' * 43}="
PRESHARED_KEY = f"{'F' * 43}="
SERVER_PUBLIC_KEY = f"{'D' * 43}="

LA = Node(id="us-la", name="美国-洛杉矶", region="US", agent_url="http://127.0.0.1:18765", enabled=True, order=10)
TOKYO = Node(id="jp-tyo", name="日本-东京", region="JP", agent_url="http://127.0.0.1:18767", enabled=True, order=20)
PARKED = Node(id="parked", name="停用节点", region="", agent_url="http://127.0.0.1:18799", enabled=False, order=90)
NODES = (LA, TOKYO, PARKED)


def agent_status_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "ok",
        "generated_at": "2026-07-15T00:00:00Z",
        "agent_version": "0.4.0",
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
            "listen_port": 62000,
            "expected_listen_port": 62000,
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
    payload.update(overrides)
    return payload


def agent_node_info() -> dict[str, object]:
    return {
        "node_schema": 1,
        "interface": "awg0",
        "public_key": SERVER_PUBLIC_KEY,
        "endpoint": "45.76.173.147:62000",
        "listen_port": 62000,
        "mtu": 1280,
        "obfuscation": {
            "Jc": 0, "Jmin": 0, "Jmax": 0,
            "S1": 79, "S2": 121, "S3": 37, "S4": 0,
            "H1": 1, "H2": 2, "H3": 3, "H4": 4,
        },
        "private_key": "must-never-leak",
    }


def agent_device(**overrides: object) -> dict[str, object]:
    device: dict[str, object] = {
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
    device.update(overrides)
    return device


ENROLL_REQUEST = {
    "name": "  办公电脑  ",
    "platform": "windows",
    "device_id": DEVICE_ID,
    "public_key": PUBLIC_KEY,
    "architecture": "amd64",
    "agent_version": "0.3.0-pilot",
    "owner_id": "attacker",
    "private_key": "attacker-private-key",
}


class VpnGatewayTests(unittest.TestCase):
    def test_status_requires_a_cookie_without_calling_upstreams(self) -> None:
        calls: list[str] = []

        def fake_fetcher(url, _method, _headers, _payload, _timeout):
            calls.append(url)
            return 200, {}

        with self.assertRaises(GatewayError) as context:
            get_authenticated_vpn_status(None, nodes=NODES, fetcher=fake_fetcher)
        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(calls, [])

    def test_all_authenticated_users_can_read_status_without_role_checks(self) -> None:
        calls: list[tuple[str, str, dict[str, str]]] = []

        def fake_fetcher(url, method, headers, _payload, _timeout):
            calls.append((url, method, dict(headers)))
            if url == AUTH_URL:
                return 200, {"id": "user_any", "role": "ordinary_user"}
            if url == LA.status_url:
                return 200, agent_status_payload()
            raise AssertionError(url)

        payload = get_authenticated_vpn_status(
            "barong_session=opaque-value",
            nodes=NODES,
            fetcher=fake_fetcher,
        )
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["node_id"], "us-la")
        self.assertEqual(calls[0][2], {"Cookie": "barong_session=opaque-value"})
        self.assertEqual(calls[1][2], {})

    def test_nodes_are_listed_from_the_registry_with_degraded_passed_through(self) -> None:
        def fake_fetcher(url, _method, _headers, _payload, _timeout):
            if url == AUTH_URL:
                return 200, {"id": "user_any"}
            if url == LA.status_url:
                return 200, agent_status_payload()
            if url == TOKYO.status_url:
                return 503, agent_status_payload(status="degraded", warnings=["vpn_status_unavailable"])
            raise AssertionError(url)

        result = get_authenticated_nodes("session=opaque", nodes=NODES, fetcher=fake_fetcher)
        by_id = {entry["id"]: entry for entry in result["nodes"]}
        self.assertEqual([entry["id"] for entry in result["nodes"]], ["us-la", "jp-tyo", "parked"])
        self.assertEqual(by_id["us-la"]["name"], "美国-洛杉矶")
        self.assertEqual(by_id["us-la"]["status"]["status"], "ok")
        self.assertEqual(by_id["jp-tyo"]["status"]["status"], "degraded")
        self.assertEqual(by_id["jp-tyo"]["status"]["warnings"], ["vpn_status_unavailable"])
        self.assertFalse(by_id["parked"]["enabled"])
        self.assertEqual(by_id["parked"]["status"]["status"], "unreachable")
        serialized = repr(result)
        self.assertNotIn("agent_url", serialized)
        self.assertNotIn("18765", serialized)
        self.assertNotIn("must-never-leak", serialized)

    def test_unreachable_node_is_reported_not_raised(self) -> None:
        def fake_fetcher(url, _method, _headers, _payload, _timeout):
            if url == AUTH_URL:
                return 200, {"id": "user_any"}
            if url == LA.status_url:
                return 200, agent_status_payload()
            raise UpstreamUnavailable

        result = get_authenticated_nodes("session=opaque", nodes=NODES, fetcher=fake_fetcher)
        by_id = {entry["id"]: entry for entry in result["nodes"]}
        self.assertEqual(by_id["jp-tyo"]["status"]["status"], "unreachable")
        self.assertEqual(by_id["us-la"]["status"]["status"], "ok")

    def test_device_list_aggregates_nodes_and_is_scoped_to_authenticated_identity(self) -> None:
        calls: list[tuple[str, str, dict[str, str], object]] = []

        def fake_fetcher(url, method, headers, payload, _timeout):
            calls.append((url, method, dict(headers), payload))
            if url == AUTH_URL:
                return 200, {"id": "user-123", "organization_id": "ignored"}
            if url == LA.devices_url:
                return 200, {"devices": [agent_device()]}
            if url == TOKYO.devices_url:
                return 200, {"devices": [agent_device(id="3b2b6c1c-6c4a-4c3b-9a1a-9d4a2b0c7e11", address="10.66.66.3/32")]}
            raise AssertionError(url)

        result = get_authenticated_devices(
            "session=opaque",
            nodes=NODES,
            agent_token=AGENT_TOKEN,
            fetcher=fake_fetcher,
        )
        self.assertEqual({d["node_id"] for d in result["devices"]}, {"us-la", "jp-tyo"})
        self.assertEqual(result["unavailable_nodes"], [])
        agent_calls = [call for call in calls if call[0] != AUTH_URL]
        self.assertEqual(len(agent_calls), 2)
        for _url, _method, headers, _payload in agent_calls:
            self.assertEqual(headers["X-Barong-User-ID"], "user-123")
            self.assertEqual(headers["Authorization"], f"Bearer {AGENT_TOKEN}")
        self.assertFalse(any(call[0] == PARKED.devices_url for call in calls))
        serialized = repr(result)
        self.assertNotIn("owner_id", serialized)
        self.assertNotIn("public_key", serialized)
        self.assertNotIn("preshared_key", serialized)
        self.assertNotIn(AGENT_TOKEN, serialized)

    def test_device_list_degrades_when_one_node_is_down(self) -> None:
        def fake_fetcher(url, _method, _headers, _payload, _timeout):
            if url == AUTH_URL:
                return 200, {"id": "user-123"}
            if url == LA.devices_url:
                return 200, {"devices": [agent_device()]}
            raise UpstreamUnavailable

        result = get_authenticated_devices(
            "session=opaque", nodes=NODES, agent_token=AGENT_TOKEN, fetcher=fake_fetcher
        )
        self.assertEqual(len(result["devices"]), 1)
        self.assertEqual(result["unavailable_nodes"], ["jp-tyo"])

    def test_update_uses_authenticated_owner_and_routes_to_the_owning_node(self) -> None:
        calls: list[tuple[str, str, dict[str, str], object]] = []

        def fake_fetcher(url, method, headers, payload, _timeout):
            calls.append((url, method, dict(headers), payload))
            if url == AUTH_URL:
                return 200, {"id": "user-123"}
            if url == f"{LA.devices_url}/{DEVICE_ID}":
                return 404, {"error": "device_not_found"}
            if url == f"{TOKYO.devices_url}/{DEVICE_ID}":
                return 200, {"device": {**agent_device(), "enabled": False}}
            raise AssertionError(url)

        result = update_authenticated_device(
            "session=opaque",
            DEVICE_ID,
            {"enabled": False, "owner_id": "attacker"},
            nodes=NODES,
            agent_token=AGENT_TOKEN,
            fetcher=fake_fetcher,
        )
        patches = [call for call in calls if call[1] == "PATCH"]
        self.assertEqual(len(patches), 2)
        self.assertEqual(patches[0][3], {"enabled": False})
        self.assertEqual(patches[0][2]["X-Barong-User-ID"], "user-123")
        self.assertFalse(result["device"]["enabled"])
        self.assertEqual(result["device"]["node_id"], "jp-tyo")

    def test_native_enrollment_returns_schema_2_with_node_parameters(self) -> None:
        calls: list[tuple[str, str, dict[str, str], object]] = []

        def fake_fetcher(url, method, headers, payload, _timeout):
            calls.append((url, method, dict(headers), payload))
            if url == AUTH_URL:
                return 200, {"id": "user-123"}
            if url == TOKYO.node_url:
                return 200, agent_node_info()
            if url == f"{TOKYO.devices_url}/enroll":
                return 201, {
                    "device": agent_device(),
                    "provisioning": {
                        "schema_version": 1,
                        "device_id": DEVICE_ID,
                        "address": "10.66.66.2/32",
                        "preshared_key": PRESHARED_KEY,
                    },
                    "one_time": True,
                    "private_key": "must-never-exist",
                }
            raise AssertionError(url)

        result = enroll_authenticated_device(
            "session=opaque",
            {**ENROLL_REQUEST, "node_id": "jp-tyo"},
            nodes=NODES,
            agent_token=AGENT_TOKEN,
            fetcher=fake_fetcher,
        )
        enroll_call = next(call for call in calls if call[1] == "POST")
        self.assertEqual(
            enroll_call[3],
            {
                "name": "办公电脑",
                "platform": "windows",
                "device_id": DEVICE_ID,
                "public_key": PUBLIC_KEY,
                "architecture": "amd64",
                "agent_version": "0.3.0-pilot",
            },
        )
        self.assertEqual(enroll_call[2]["X-Barong-User-ID"], "user-123")
        provisioning = result["provisioning"]
        self.assertEqual(provisioning["schema_version"], 2)
        self.assertEqual(provisioning["preshared_key"], PRESHARED_KEY)
        self.assertEqual(provisioning["dns"], ["1.1.1.1", "1.0.0.1"])
        self.assertEqual(
            provisioning["node"],
            {
                "id": "jp-tyo",
                "name": "日本-东京",
                "endpoint": "45.76.173.147:62000",
                "public_key": SERVER_PUBLIC_KEY,
                "mtu": 1280,
                "obfuscation": agent_node_info()["obfuscation"],
            },
        )
        self.assertEqual(result["device"]["node_id"], "jp-tyo")
        self.assertNotIn("private_key", repr(result))
        self.assertNotIn("must-never-leak", repr(result))

    def test_enrollment_without_node_falls_back_to_the_default_node(self) -> None:
        def fake_fetcher(url, _method, _headers, _payload, _timeout):
            if url == AUTH_URL:
                return 200, {"id": "user-123"}
            if url == LA.node_url:
                return 200, agent_node_info()
            if url == f"{LA.devices_url}/enroll":
                return 201, {
                    "device": agent_device(),
                    "provisioning": {
                        "schema_version": 1,
                        "device_id": DEVICE_ID,
                        "address": "10.66.66.2/32",
                        "preshared_key": PRESHARED_KEY,
                    },
                    "one_time": True,
                }
            raise AssertionError(url)

        result = enroll_authenticated_device(
            "session=opaque", ENROLL_REQUEST, nodes=NODES, agent_token=AGENT_TOKEN, fetcher=fake_fetcher
        )
        self.assertEqual(result["provisioning"]["node"]["id"], "us-la")

    def test_enrollment_rejects_unknown_or_disabled_nodes(self) -> None:
        def fake_fetcher(url, _method, _headers, _payload, _timeout):
            if url == AUTH_URL:
                return 200, {"id": "user-123"}
            raise AssertionError("agent must not be called")

        for node_id, expected in (("nope", 400), ("parked", 409), ("../x", 400)):
            with self.assertRaises(GatewayError) as context:
                enroll_authenticated_device(
                    "session=opaque",
                    {**ENROLL_REQUEST, "node_id": node_id},
                    nodes=NODES,
                    agent_token=AGENT_TOKEN,
                    fetcher=fake_fetcher,
                )
            self.assertEqual(context.exception.status_code, expected, node_id)

    def test_invalid_session_never_reaches_the_agent(self) -> None:
        def fake_fetcher(url, _method, _headers, _payload, _timeout):
            if url == AUTH_URL:
                return 401, None
            raise AssertionError("VPN agent must not be called")

        with self.assertRaises(GatewayError) as context:
            get_authenticated_devices(
                "invalid=1",
                nodes=NODES,
                agent_token=AGENT_TOKEN,
                fetcher=fake_fetcher,
            )
        self.assertEqual(context.exception.status_code, 401)

    def test_agent_outputs_are_allowlisted(self) -> None:
        status = sanitize_vpn_status(agent_status_payload())
        devices = sanitize_device_list({"devices": [agent_device()]}, node_id="us-la")
        node_info = sanitize_node_info(agent_node_info())
        serialized = repr((status, devices, node_info))
        self.assertNotIn("owner_id", serialized)
        self.assertNotIn("preshared_key", serialized)
        self.assertNotIn("must-never-leak", serialized)
        self.assertEqual(status["vpn"]["interface"], "awg0")
        self.assertEqual(devices["devices"][0]["node_id"], "us-la")
        self.assertEqual(node_info["endpoint"], "45.76.173.147:62000")
        with self.assertRaises(GatewayError):
            sanitize_node_info({**agent_node_info(), "endpoint": "evil.example.com"})
        with self.assertRaises(GatewayError):
            sanitize_node_info({**agent_node_info(), "obfuscation": {"Jc": 1}})

    def test_agent_outage_returns_generic_unavailable_error(self) -> None:
        def fake_fetcher(url, _method, _headers, _payload, _timeout):
            if url == AUTH_URL:
                return 200, {"id": "user_any"}
            raise UpstreamUnavailable

        with self.assertRaises(GatewayError) as context:
            get_authenticated_vpn_status("session=opaque", nodes=NODES, fetcher=fake_fetcher)
        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(context.exception.detail, "VPN status temporarily unavailable.")

    def test_health_reports_every_enabled_node(self) -> None:
        def fake_fetcher(_url, _method, _headers, _payload, _timeout):
            return 200, {"status": "ok", "secret": "not-forwarded"}

        status_code, payload = dependency_health(nodes=NODES, fetcher=fake_fetcher)
        self.assertEqual(status_code, 200)
        self.assertEqual(
            payload["dependencies"],
            {"console_backend": "ok", "vpn_agent:us-la": "ok", "vpn_agent:jp-tyo": "ok"},
        )
        self.assertEqual(payload["node_count"], 2)
        self.assertNotIn("secret", repr(payload))

    def test_nodes_file_is_validated(self) -> None:
        nodes = parse_nodes(
            {"nodes": [
                {"id": "jp-tyo", "name": "日本-东京", "region": "JP", "agent_url": "http://127.0.0.1:18767", "order": 20},
                {"id": "us-la", "name": "美国-洛杉矶", "region": "US", "agent_url": "http://127.0.0.1:18765", "order": 10},
            ]}
        )
        self.assertEqual([node.id for node in nodes], ["us-la", "jp-tyo"])
        for bad in (
            {"nodes": []},
            {"nodes": [{"id": "US LA", "name": "x", "agent_url": "http://127.0.0.1:1"}]},
            {"nodes": [{"id": "us-la", "name": "x", "agent_url": "http://45.76.173.147:8765"}]},
            {"nodes": [{"id": "a-b", "name": "x", "agent_url": "http://127.0.0.1:1"}, {"id": "a-b", "name": "y", "agent_url": "http://127.0.0.1:2"}]},
        ):
            with self.assertRaises(RuntimeError):
                parse_nodes(bad)
        self.assertEqual(LEGACY_NODES[0].id, "us-la")


if __name__ == "__main__":
    unittest.main()
