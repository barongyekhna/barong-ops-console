from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.vpn_agent import DeviceError, DeviceManager, INTERFACE, StatusCommandError


PRIVATE_KEY = f"{'A' * 43}="
PUBLIC_KEY = f"{'B' * 43}="
PRESHARED_KEY = f"{'C' * 43}="
SERVER_PUBLIC_KEY = f"{'D' * 43}="
NATIVE_PUBLIC_KEY = f"{'E' * 43}="
NATIVE_DEVICE_ID = "71a13b3b-5db0-4bda-9a8f-a2225fdd3d72"


class FakeAwg:
    def __init__(self) -> None:
        self.commands: list[tuple[tuple[str, ...], str | None]] = []
        self.peers: set[str] = set()

    def __call__(self, command: tuple[str, ...], input_text: str | None) -> str:
        self.commands.append((command, input_text))
        if command == ("/usr/bin/awg", "genkey"):
            return PRIVATE_KEY
        if command == ("/usr/bin/awg", "pubkey"):
            self.assert_private_stdin(input_text)
            return PUBLIC_KEY
        if command == ("/usr/bin/awg", "genpsk"):
            return PRESHARED_KEY
        if command == ("/usr/bin/awg", "show", INTERFACE, "public-key"):
            return SERVER_PUBLIC_KEY
        if command == ("/usr/bin/awg", "showconf", INTERFACE):
            return "\n".join(
                (
                    "PrivateKey = must-not-leak",
                    "Jc = 0",
                    "Jmin = 0",
                    "Jmax = 0",
                    "S1 = 79",
                    "S2 = 121",
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

    @staticmethod
    def assert_private_stdin(value: str | None) -> None:
        if value != f"{PRIVATE_KEY}\n":
            raise AssertionError("private key was not passed through stdin")


class DeviceManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runner = FakeAwg()
        self.manager = DeviceManager(
            state_path=self.root / "state" / "devices.json",
            runtime_dir=self.root / "run",
            command_runner=self.runner,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create(self, owner: str = "user-one") -> dict[str, object]:
        return self.manager.create_device(
            owner,
            name="办公电脑",
            platform="windows",
        )

    def test_create_adds_only_an_awg0_peer_and_never_persists_private_key(self) -> None:
        result = self.create()
        configuration = result["configuration"]
        self.assertIsInstance(configuration, str)
        self.assertIn(PRIVATE_KEY, configuration)
        state_text = (self.root / "state" / "devices.json").read_text("utf-8")
        self.assertNotIn(PRIVATE_KEY, state_text)
        self.assertNotIn(SERVER_PUBLIC_KEY, state_text)
        self.assertIn(PUBLIC_KEY, state_text)
        self.assertIn(PRESHARED_KEY, state_text)
        commands = [command for command, _input in self.runner.commands]
        self.assertTrue(
            any(command[:4] == ("/usr/bin/awg", "set", "awg0", "peer") for command in commands)
        )
        self.assertFalse(any("wg0" in command for command in commands))
        self.assertFalse(any("systemctl" in command for command in commands))

    def test_owner_can_only_list_their_own_devices(self) -> None:
        self.create("user-one")
        self.assertEqual(len(self.manager.list_devices("user-one")), 1)
        self.assertEqual(self.manager.list_devices("user-two"), [])

    def test_disable_removes_only_the_selected_managed_peer(self) -> None:
        result = self.create()
        device = result["device"]
        self.assertIsInstance(device, dict)
        device_id = device["id"]
        self.assertIsInstance(device_id, str)
        disabled = self.manager.set_device_enabled(
            "user-one", device_id, enabled=False
        )
        self.assertFalse(disabled["enabled"])
        self.assertNotIn(PUBLIC_KEY, self.runner.peers)
        state = json.loads((self.root / "state" / "devices.json").read_text("utf-8"))
        self.assertFalse(state["devices"][0]["enabled"])

    def test_another_owner_cannot_disable_the_device(self) -> None:
        result = self.create()
        device_id = result["device"]["id"]
        with self.assertRaises(DeviceError) as context:
            self.manager.set_device_enabled("user-two", device_id, enabled=False)
        self.assertEqual(context.exception.status_code, 404)
        self.assertIn(PUBLIC_KEY, self.runner.peers)

    def test_reconcile_only_restores_missing_managed_awg0_peers(self) -> None:
        self.create()
        self.runner.peers.clear()
        before = len(self.runner.commands)
        self.manager.reconcile()
        after_commands = [command for command, _input in self.runner.commands[before:]]
        self.assertIn(PUBLIC_KEY, self.runner.peers)
        self.assertTrue(
            any(command[:4] == ("/usr/bin/awg", "set", "awg0", "peer") for command in after_commands)
        )

    def test_native_enrollment_uses_client_public_key_and_never_generates_private_key(self) -> None:
        result = self.manager.enroll_native_device(
            "user-one",
            name="Windows 办公电脑",
            platform="windows",
            device_id=NATIVE_DEVICE_ID,
            public_key=NATIVE_PUBLIC_KEY,
            architecture="amd64",
            agent_version="0.2.0-pilot",
        )
        provisioning = result["provisioning"]
        self.assertEqual(result["device"]["id"], NATIVE_DEVICE_ID)
        self.assertEqual(provisioning["device_id"], NATIVE_DEVICE_ID)
        self.assertEqual(provisioning["preshared_key"], PRESHARED_KEY)
        state_text = (self.root / "state" / "devices.json").read_text("utf-8")
        self.assertIn(NATIVE_PUBLIC_KEY, state_text)
        commands = [command for command, _input in self.runner.commands]
        self.assertNotIn(("/usr/bin/awg", "genkey"), commands)
        self.assertNotIn(("/usr/bin/awg", "pubkey"), commands)
        self.assertIn(NATIVE_PUBLIC_KEY, self.runner.peers)
        self.assertFalse(any("wg0" in command for command in commands))

    def test_native_enrollment_retry_is_idempotent_for_the_same_owner_and_key(self) -> None:
        arguments = {
            "name": "Windows 办公电脑",
            "platform": "windows",
            "device_id": NATIVE_DEVICE_ID,
            "public_key": NATIVE_PUBLIC_KEY,
            "architecture": "amd64",
            "agent_version": "0.2.0-pilot",
        }
        first = self.manager.enroll_native_device("user-one", **arguments)
        before = len(self.runner.commands)
        second = self.manager.enroll_native_device("user-one", **arguments)
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(first["provisioning"], second["provisioning"])
        repeated_commands = self.runner.commands[before:]
        self.assertFalse(
            any(command[:4] == ("/usr/bin/awg", "set", "awg0", "peer") for command, _ in repeated_commands)
        )

    def test_native_device_identity_cannot_be_claimed_by_another_owner(self) -> None:
        self.manager.enroll_native_device(
            "user-one",
            name="Windows 办公电脑",
            platform="windows",
            device_id=NATIVE_DEVICE_ID,
            public_key=NATIVE_PUBLIC_KEY,
            architecture="amd64",
            agent_version="0.2.0-pilot",
        )
        with self.assertRaises(DeviceError) as context:
            self.manager.enroll_native_device(
                "user-two",
                name="冒用设备",
                platform="windows",
                device_id=NATIVE_DEVICE_ID,
                public_key=NATIVE_PUBLIC_KEY,
                architecture="amd64",
                agent_version="0.2.0-pilot",
            )
        self.assertEqual(context.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
