from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.vpn_agent import DeviceError, DeviceManager, INTERFACE, StatusCommandError


PRESHARED_KEY = f"{'C' * 43}="
SECOND_PRESHARED_KEY = f"{'F' * 43}="
SERVER_PUBLIC_KEY = f"{'D' * 43}="
NATIVE_PUBLIC_KEY = f"{'E' * 43}="
NATIVE_DEVICE_ID = "71a13b3b-5db0-4bda-9a8f-a2225fdd3d72"
LISTEN_PORT = 62000


class FakeAwg:
    def __init__(self) -> None:
        self.commands: list[tuple[tuple[str, ...], str | None]] = []
        self.peers: set[str] = set()
        self.psk_sequence = [PRESHARED_KEY, SECOND_PRESHARED_KEY]

    def __call__(self, command: tuple[str, ...], input_text: str | None) -> str:
        self.commands.append((command, input_text))
        if command == ("/usr/bin/awg", "genpsk"):
            return self.psk_sequence.pop(0) if self.psk_sequence else SECOND_PRESHARED_KEY
        if command == ("/usr/bin/awg", "show", INTERFACE, "public-key"):
            return SERVER_PUBLIC_KEY
        if command == ("/usr/bin/awg", "show", INTERFACE, "listen-port"):
            return str(LISTEN_PORT)
        if command == ("/usr/bin/awg", "showconf", INTERFACE):
            return "\n".join(
                (
                    "PrivateKey = must-not-leak",
                    "Jc = 0",
                    "Jmin = 0",
                    "Jmax = 0",
                    "S1 = 79",
                    "S2 = 121",
                    "S3 = 37",
                    "S4 = 0",
                    "H1 = 1",
                    "H2 = 2",
                    "H3 = 3",
                    "H4 = 4",
                )
            )
        if command == ("/usr/bin/awg", "show", INTERFACE, "peers"):
            return "\n".join(sorted(self.peers))
        if command == ("/usr/bin/awg", "show", INTERFACE, "latest-handshakes"):
            return ""
        if command == ("/usr/bin/awg", "show", INTERFACE, "transfer"):
            return ""
        if command[:4] == ("/usr/bin/awg", "set", INTERFACE, "peer"):
            public_key = command[4]
            if command[-1] == "remove":
                self.peers.discard(public_key)
            else:
                self.peers.add(public_key)
            return ""
        raise StatusCommandError(f"unexpected command: {command!r}")


ENROLLMENT = {
    "name": "Windows 办公电脑",
    "platform": "windows",
    "device_id": NATIVE_DEVICE_ID,
    "public_key": NATIVE_PUBLIC_KEY,
    "architecture": "amd64",
    "agent_version": "0.3.0-pilot",
}


class DeviceManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runner = FakeAwg()
        self.manager = DeviceManager(
            state_path=self.root / "state" / "devices.json",
            runtime_dir=self.root / "run",
            public_host="45.76.173.147",
            command_runner=self.runner,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def enroll(self, owner: str = "user-one") -> dict[str, object]:
        return self.manager.enroll_native_device(owner, **ENROLLMENT)

    def test_manager_has_no_server_side_device_creation(self) -> None:
        # Every device is the signed-in client itself; the server never
        # generates a client private key.
        self.assertFalse(hasattr(self.manager, "create_device"))
        self.enroll()
        commands = [command for command, _input in self.runner.commands]
        self.assertNotIn(("/usr/bin/awg", "genkey"), commands)
        self.assertNotIn(("/usr/bin/awg", "pubkey"), commands)

    def test_owner_can_only_list_their_own_devices(self) -> None:
        self.enroll("user-one")
        self.assertEqual(len(self.manager.list_devices("user-one")), 1)
        self.assertEqual(self.manager.list_devices("user-two"), [])

    def test_disable_removes_only_the_selected_managed_peer(self) -> None:
        self.enroll()
        disabled = self.manager.set_device_enabled(
            "user-one", NATIVE_DEVICE_ID, enabled=False
        )
        self.assertFalse(disabled["enabled"])
        self.assertNotIn(NATIVE_PUBLIC_KEY, self.runner.peers)
        state = json.loads((self.root / "state" / "devices.json").read_text("utf-8"))
        self.assertFalse(state["devices"][0]["enabled"])

    def test_another_owner_cannot_disable_the_device(self) -> None:
        self.enroll()
        with self.assertRaises(DeviceError) as context:
            self.manager.set_device_enabled("user-two", NATIVE_DEVICE_ID, enabled=False)
        self.assertEqual(context.exception.status_code, 404)
        self.assertIn(NATIVE_PUBLIC_KEY, self.runner.peers)

    def test_reconcile_only_restores_missing_managed_awg0_peers(self) -> None:
        self.enroll()
        self.runner.peers.clear()
        before = len(self.runner.commands)
        self.manager.reconcile()
        after_commands = [command for command, _input in self.runner.commands[before:]]
        self.assertIn(NATIVE_PUBLIC_KEY, self.runner.peers)
        self.assertTrue(
            any(command[:4] == ("/usr/bin/awg", "set", "awg0", "peer") for command in after_commands)
        )
        self.assertFalse(any("wg0" in command for command in after_commands))
        self.assertFalse(any("systemctl" in command for command in after_commands))

    def test_native_enrollment_uses_client_public_key_and_never_generates_private_key(self) -> None:
        result = self.enroll()
        provisioning = result["provisioning"]
        self.assertEqual(result["device"]["id"], NATIVE_DEVICE_ID)
        self.assertEqual(provisioning["device_id"], NATIVE_DEVICE_ID)
        self.assertEqual(provisioning["preshared_key"], PRESHARED_KEY)
        state_text = (self.root / "state" / "devices.json").read_text("utf-8")
        self.assertIn(NATIVE_PUBLIC_KEY, state_text)
        self.assertNotIn(SERVER_PUBLIC_KEY, state_text)
        self.assertIn(NATIVE_PUBLIC_KEY, self.runner.peers)
        self.assertFalse(result["idempotent_replay"])

    def test_native_enrollment_replay_rotates_the_preshared_key(self) -> None:
        # A reinstall or node switch re-enrolls the same device id and public
        # key; the old PSK must stop working and the peer is re-applied.
        first = self.enroll()
        before = len(self.runner.commands)
        second = self.enroll()
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(second["provisioning"]["address"], first["provisioning"]["address"])
        self.assertEqual(second["provisioning"]["preshared_key"], SECOND_PRESHARED_KEY)
        self.assertNotEqual(
            second["provisioning"]["preshared_key"], first["provisioning"]["preshared_key"]
        )
        repeated = [command for command, _ in self.runner.commands[before:]]
        self.assertTrue(
            any(command[:4] == ("/usr/bin/awg", "set", "awg0", "peer") for command in repeated)
        )
        state = json.loads((self.root / "state" / "devices.json").read_text("utf-8"))
        self.assertEqual(len(state["devices"]), 1)
        self.assertEqual(state["devices"][0]["preshared_key"], SECOND_PRESHARED_KEY)
        self.assertTrue(state["devices"][0]["enabled"])

    def test_native_device_identity_cannot_be_claimed_by_another_owner(self) -> None:
        self.enroll("user-one")
        with self.assertRaises(DeviceError) as context:
            self.manager.enroll_native_device("user-two", **{**ENROLLMENT, "name": "冒用设备"})
        self.assertEqual(context.exception.status_code, 409)

    def test_node_info_comes_from_the_live_interface_and_never_leaks_private_key(self) -> None:
        node = self.manager.node_info()
        self.assertEqual(node["node_schema"], 1)
        self.assertEqual(node["endpoint"], f"45.76.173.147:{LISTEN_PORT}")
        self.assertEqual(node["listen_port"], LISTEN_PORT)
        self.assertEqual(node["public_key"], SERVER_PUBLIC_KEY)
        self.assertEqual(node["mtu"], 1280)
        self.assertEqual(
            node["obfuscation"],
            {
                "Jc": 0, "Jmin": 0, "Jmax": 0,
                "S1": 79, "S2": 121, "S3": 37, "S4": 0,
                "H1": 1, "H2": 2, "H3": 3, "H4": 4,
            },
        )
        self.assertNotIn("must-not-leak", json.dumps(node))

    def test_public_host_is_validated(self) -> None:
        with self.assertRaises(ValueError):
            DeviceManager(
                state_path=self.root / "x.json",
                runtime_dir=self.root / "run",
                public_host="not a host",
                command_runner=self.runner,
            )


if __name__ == "__main__":
    unittest.main()
