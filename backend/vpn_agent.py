from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit


VERSION = "0.3.1"
BIND_HOST = "127.0.0.1"
BIND_PORT = 8765
INTERFACE = "awg0"
SERVICE = "awg-quick@awg0.service"
EXPECTED_PORT = 62000
DEFAULT_ENDPOINT = "45.76.173.147:62000"
DEFAULT_DNS = "1.1.1.1"
DEFAULT_STATE_PATH = Path("/var/lib/barong-vpn-agent/devices.json")
DEFAULT_RUNTIME_DIR = Path("/run/barong-vpn-agent")
COMMAND_TIMEOUT_SECONDS = 5
MAX_BODY_BYTES = 16_384
MAX_DEVICES_PER_OWNER = 10
RECONCILE_INTERVAL_SECONDS = 30
PLATFORMS = {"windows", "macos", "ios", "android", "other"}
KEY_PATTERN = re.compile(r"^[A-Za-z0-9+/]{43}=$")
OWNER_PATTERN = re.compile(r"^[A-Za-z0-9._:@-]{1,128}$")
AGENT_FIELD_PATTERN = re.compile(r"^[A-Za-z0-9._+-]{1,32}$")
DEVICE_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
OBFUSCATION_FIELDS = ("Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4")
LOGGER = logging.getLogger("barong_vpn_agent")


class StatusCommandError(RuntimeError):
    pass


class DeviceError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


CommandRunner = Callable[[tuple[str, ...], Optional[str]], str]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


def iso_utc_from_epoch(value: int) -> str | None:
    if value <= 0:
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def run_command(command: tuple[str, ...], input_text: str | None = None) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            input=input_text,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StatusCommandError("command unavailable") from exc
    if completed.returncode != 0:
        raise StatusCommandError("command failed")
    return completed.stdout.strip()


def run_status_command(command: Iterable[str]) -> str:
    return run_command(tuple(command))


def parse_interface_address(raw_json: str) -> str | None:
    try:
        records = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise StatusCommandError("invalid interface status") from exc
    if not isinstance(records, list):
        raise StatusCommandError("invalid interface status")
    for record in records:
        if not isinstance(record, dict):
            continue
        for address in record.get("addr_info", []):
            if not isinstance(address, dict):
                continue
            if address.get("family") == "inet" and address.get("scope") == "global":
                local = address.get("local")
                prefix = address.get("prefixlen")
                if isinstance(local, str) and isinstance(prefix, int):
                    return f"{local}/{prefix}"
    return None


def parse_handshakes(raw: str, now_epoch: int) -> tuple[int, int | None]:
    recent_count = 0
    latest_epoch: int | None = None
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            handshake_epoch = int(fields[1])
        except ValueError:
            continue
        if handshake_epoch <= 0:
            continue
        latest_epoch = max(latest_epoch or 0, handshake_epoch)
        if 0 <= now_epoch - handshake_epoch <= 180:
            recent_count += 1
    return recent_count, latest_epoch


def parse_transfer(raw: str) -> tuple[int, int]:
    received_bytes = 0
    sent_bytes = 0
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            received_bytes += int(fields[1])
            sent_bytes += int(fields[2])
        except ValueError:
            continue
    return received_bytes, sent_bytes


def collect_status(command_runner: CommandRunner = run_command) -> dict[str, Any]:
    now = utc_now()
    warnings: list[str] = []

    try:
        active_state = command_runner(
            ("/usr/bin/systemctl", "show", SERVICE, "--property=ActiveState", "--value"),
            None,
        )
        sub_state = command_runner(
            ("/usr/bin/systemctl", "show", SERVICE, "--property=SubState", "--value"),
            None,
        )
        active_since = command_runner(
            (
                "/usr/bin/systemctl",
                "show",
                SERVICE,
                "--property=ActiveEnterTimestamp",
                "--value",
            ),
            None,
        ) or None
    except StatusCommandError:
        active_state = "unknown"
        sub_state = "unknown"
        active_since = None
        warnings.append("service_status_unavailable")

    try:
        address = parse_interface_address(
            command_runner(
                ("/usr/sbin/ip", "-j", "address", "show", "dev", INTERFACE),
                None,
            )
        )
    except StatusCommandError:
        address = None
        warnings.append("interface_status_unavailable")

    try:
        listen_port = int(
            command_runner(("/usr/bin/awg", "show", INTERFACE, "listen-port"), None)
        )
        peer_keys = command_runner(("/usr/bin/awg", "show", INTERFACE, "peers"), None)
        peer_count = len(peer_keys.split()) if peer_keys else 0
        handshake_output = command_runner(
            ("/usr/bin/awg", "show", INTERFACE, "latest-handshakes"), None
        )
        recent_count, latest_handshake_epoch = parse_handshakes(
            handshake_output, int(now.timestamp())
        )
        transfer_output = command_runner(
            ("/usr/bin/awg", "show", INTERFACE, "transfer"), None
        )
        received_bytes, sent_bytes = parse_transfer(transfer_output)
    except (StatusCommandError, ValueError):
        listen_port = None
        peer_count = None
        recent_count = None
        latest_handshake_epoch = None
        received_bytes = None
        sent_bytes = None
        warnings.append("vpn_status_unavailable")

    healthy = (
        active_state == "active"
        and address is not None
        and listen_port == EXPECTED_PORT
        and not warnings
    )
    return {
        "status": "ok" if healthy else "degraded",
        "generated_at": iso_utc(now),
        "agent_version": VERSION,
        "vpn": {
            "interface": INTERFACE,
            "service": {
                "active_state": active_state,
                "sub_state": sub_state,
                "active_since": active_since,
            },
            "address": address,
            "listen_port": listen_port,
            "expected_listen_port": EXPECTED_PORT,
            "peer_count": peer_count,
            "recently_active_peer_count": recent_count,
            "latest_handshake_at": iso_utc_from_epoch(latest_handshake_epoch or 0),
            "transfer": {
                "received_bytes": received_bytes,
                "sent_bytes": sent_bytes,
            },
        },
        "warnings": warnings,
    }


def _valid_key(value: object) -> bool:
    return isinstance(value, str) and KEY_PATTERN.fullmatch(value) is not None


def _validated_owner(value: object) -> str:
    if not isinstance(value, str) or OWNER_PATTERN.fullmatch(value) is None:
        raise DeviceError(400, "invalid_owner", "Invalid device owner.")
    return value


def _validated_name(value: object) -> str:
    if not isinstance(value, str):
        raise DeviceError(400, "invalid_name", "Device name is required.")
    normalized = " ".join(value.strip().split())
    if not 1 <= len(normalized) <= 64:
        raise DeviceError(400, "invalid_name", "Device name must be 1-64 characters.")
    return normalized


def _validated_platform(value: object) -> str:
    if not isinstance(value, str) or value not in PLATFORMS:
        raise DeviceError(400, "invalid_platform", "Unsupported device platform.")
    return value


def _validated_device_id(value: object) -> str:
    if not isinstance(value, str) or DEVICE_ID_PATTERN.fullmatch(value) is None:
        raise DeviceError(400, "invalid_device_id", "Invalid device ID.")
    return value


def _validated_public_key(value: object) -> str:
    if not _valid_key(value):
        raise DeviceError(400, "invalid_public_key", "Invalid device public key.")
    return value


def _validated_agent_field(value: object, field: str) -> str:
    if not isinstance(value, str) or AGENT_FIELD_PATTERN.fullmatch(value) is None:
        raise DeviceError(400, f"invalid_{field}", f"Invalid {field}.")
    return value


def _parse_peer_metrics(
    handshakes: str, transfer: str
) -> dict[str, tuple[str | None, int | None, int | None]]:
    metrics: dict[str, tuple[str | None, int | None, int | None]] = {}
    epochs: dict[str, int] = {}
    for line in handshakes.splitlines():
        fields = line.split()
        if len(fields) != 2 or not _valid_key(fields[0]):
            continue
        try:
            epochs[fields[0]] = int(fields[1])
        except ValueError:
            continue
    transfers: dict[str, tuple[int, int]] = {}
    for line in transfer.splitlines():
        fields = line.split()
        if len(fields) != 3 or not _valid_key(fields[0]):
            continue
        try:
            transfers[fields[0]] = (int(fields[1]), int(fields[2]))
        except ValueError:
            continue
    for key in set(epochs) | set(transfers):
        received, sent = transfers.get(key, (0, 0))
        metrics[key] = (iso_utc_from_epoch(epochs.get(key, 0)), received, sent)
    return metrics


class DeviceManager:
    def __init__(
        self,
        *,
        state_path: Path = DEFAULT_STATE_PATH,
        runtime_dir: Path = DEFAULT_RUNTIME_DIR,
        endpoint: str = DEFAULT_ENDPOINT,
        dns: str = DEFAULT_DNS,
        command_runner: CommandRunner = run_command,
    ) -> None:
        self.state_path = state_path
        self.runtime_dir = runtime_dir
        self.endpoint = endpoint
        self.dns = dns
        self.command_runner = command_runner
        self._lock = threading.RLock()

    def _load(self) -> list[dict[str, Any]]:
        if not self.state_path.exists():
            return []
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeviceError(503, "state_unavailable", "Device state is unavailable.") from exc
        devices = payload.get("devices") if isinstance(payload, dict) else None
        version = payload.get("version") if isinstance(payload, dict) else None
        if version != 1 or not isinstance(devices, list):
            raise DeviceError(503, "state_unavailable", "Device state is unavailable.")
        return [item for item in devices if isinstance(item, dict)]

    def _save(self, devices: list[dict[str, Any]]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.state_path.parent,
                prefix="devices-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                os.fchmod(handle.fileno(), 0o600)
                json.dump(
                    {"version": 1, "devices": devices},
                    handle,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.state_path)
            os.chmod(self.state_path, 0o600)
            temp_name = None
        except OSError as exc:
            raise DeviceError(503, "state_unavailable", "Device state is unavailable.") from exc
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass

    def _run(self, command: tuple[str, ...], input_text: str | None = None) -> str:
        try:
            return self.command_runner(command, input_text)
        except StatusCommandError as exc:
            raise DeviceError(503, "vpn_unavailable", "VPN device service is unavailable.") from exc

    def _generate_credentials(self) -> tuple[str, str, str]:
        private_key = self._run(("/usr/bin/awg", "genkey"))
        public_key = self._run(("/usr/bin/awg", "pubkey"), f"{private_key}\n")
        preshared_key = self._run(("/usr/bin/awg", "genpsk"))
        if not all(_valid_key(item) for item in (private_key, public_key, preshared_key)):
            raise DeviceError(503, "key_generation_failed", "VPN key generation failed.")
        return private_key, public_key, preshared_key

    def _generate_preshared_key(self) -> str:
        preshared_key = self._run(("/usr/bin/awg", "genpsk"))
        if not _valid_key(preshared_key):
            raise DeviceError(503, "key_generation_failed", "VPN key generation failed.")
        return preshared_key

    def _apply_peer(self, public_key: str, preshared_key: str, address: str) -> None:
        if not _valid_key(public_key) or not _valid_key(preshared_key):
            raise DeviceError(503, "invalid_state", "Stored device state is invalid.")
        self.runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.runtime_dir,
                prefix="psk-",
                delete=False,
            ) as handle:
                temp_name = handle.name
                os.fchmod(handle.fileno(), 0o600)
                handle.write(f"{preshared_key}\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._run(
                (
                    "/usr/bin/awg",
                    "set",
                    INTERFACE,
                    "peer",
                    public_key,
                    "preshared-key",
                    temp_name,
                    "allowed-ips",
                    address,
                )
            )
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass

    def _remove_peer(self, public_key: str) -> None:
        if not _valid_key(public_key):
            raise DeviceError(503, "invalid_state", "Stored device state is invalid.")
        self._run(("/usr/bin/awg", "set", INTERFACE, "peer", public_key, "remove"))

    def _runtime_peers(self) -> set[str]:
        raw = self._run(("/usr/bin/awg", "show", INTERFACE, "peers"))
        return {item for item in raw.split() if _valid_key(item)}

    def _server_parameters(self) -> tuple[str, dict[str, str]]:
        server_public_key = self._run(
            ("/usr/bin/awg", "show", INTERFACE, "public-key")
        )
        if not _valid_key(server_public_key):
            raise DeviceError(503, "vpn_unavailable", "VPN server key is unavailable.")
        raw_config = self._run(("/usr/bin/awg", "showconf", INTERFACE))
        values: dict[str, str] = {}
        for line in raw_config.splitlines():
            key, separator, value = line.partition("=")
            normalized_key = key.strip()
            if separator and normalized_key in OBFUSCATION_FIELDS:
                normalized_value = value.strip()
                if re.fullmatch(r"[0-9]+", normalized_value):
                    values[normalized_key] = normalized_value
        if any(field not in values for field in OBFUSCATION_FIELDS):
            raise DeviceError(503, "vpn_unavailable", "VPN parameters are unavailable.")
        return server_public_key, values

    @staticmethod
    def _next_address(devices: list[dict[str, Any]]) -> str:
        used: set[int] = set()
        for device in devices:
            address = device.get("address")
            if not isinstance(address, str):
                continue
            match = re.fullmatch(r"10\.66\.66\.(\d{1,3})/32", address)
            if match:
                used.add(int(match.group(1)))
        for host in range(2, 255):
            if host not in used:
                return f"10.66.66.{host}/32"
        raise DeviceError(409, "address_pool_exhausted", "VPN address pool is full.")

    def _render_configuration(
        self,
        *,
        address: str,
        private_key: str,
        preshared_key: str,
        server_public_key: str,
        obfuscation: Mapping[str, str],
    ) -> str:
        interface_lines = [
            "[Interface]",
            f"PrivateKey = {private_key}",
            f"Address = {address}",
            f"DNS = {self.dns}",
        ]
        interface_lines.extend(
            f"{field} = {obfuscation[field]}" for field in OBFUSCATION_FIELDS
        )
        peer_lines = [
            "",
            "[Peer]",
            f"PublicKey = {server_public_key}",
            f"PresharedKey = {preshared_key}",
            f"Endpoint = {self.endpoint}",
            "AllowedIPs = 0.0.0.0/0",
            "PersistentKeepalive = 25",
            "",
        ]
        return "\n".join(interface_lines + peer_lines)

    @staticmethod
    def _public_device(
        device: Mapping[str, Any],
        metrics: Mapping[str, tuple[str | None, int | None, int | None]],
    ) -> dict[str, Any]:
        public_key = device.get("public_key")
        last_handshake, received_bytes, sent_bytes = metrics.get(
            public_key if isinstance(public_key, str) else "",
            (None, 0, 0),
        )
        return {
            "id": device.get("id"),
            "name": device.get("name"),
            "platform": device.get("platform"),
            "address": device.get("address"),
            "enabled": device.get("enabled") is True,
            "created_at": device.get("created_at"),
            "updated_at": device.get("updated_at"),
            "last_handshake_at": last_handshake,
            "received_bytes": received_bytes,
            "sent_bytes": sent_bytes,
        }

    def _metrics(self) -> dict[str, tuple[str | None, int | None, int | None]]:
        try:
            handshakes = self.command_runner(
                ("/usr/bin/awg", "show", INTERFACE, "latest-handshakes"), None
            )
            transfer = self.command_runner(
                ("/usr/bin/awg", "show", INTERFACE, "transfer"), None
            )
        except StatusCommandError:
            return {}
        return _parse_peer_metrics(handshakes, transfer)

    def list_devices(self, owner_id: object) -> list[dict[str, Any]]:
        owner = _validated_owner(owner_id)
        with self._lock:
            devices = [item for item in self._load() if item.get("owner_id") == owner]
            metrics = self._metrics()
            return [self._public_device(item, metrics) for item in devices]

    def create_device(
        self, owner_id: object, *, name: object, platform: object
    ) -> dict[str, Any]:
        owner = _validated_owner(owner_id)
        device_name = _validated_name(name)
        device_platform = _validated_platform(platform)
        with self._lock:
            devices = self._load()
            if sum(item.get("owner_id") == owner for item in devices) >= MAX_DEVICES_PER_OWNER:
                raise DeviceError(409, "device_limit_reached", "Device limit reached.")
            address = self._next_address(devices)
            private_key, public_key, preshared_key = self._generate_credentials()
            server_public_key, obfuscation = self._server_parameters()
            now = iso_utc()
            device = {
                "id": str(uuid.uuid4()),
                "owner_id": owner,
                "name": device_name,
                "platform": device_platform,
                "address": address,
                "public_key": public_key,
                "preshared_key": preshared_key,
                "enabled": True,
                "created_at": now,
                "updated_at": now,
            }
            self._apply_peer(public_key, preshared_key, address)
            try:
                self._save([*devices, device])
            except DeviceError:
                try:
                    self._remove_peer(public_key)
                except DeviceError:
                    LOGGER.error("failed to roll back newly created managed peer")
                raise
            return {
                "device": self._public_device(device, {}),
                "configuration": self._render_configuration(
                    address=address,
                    private_key=private_key,
                    preshared_key=preshared_key,
                    server_public_key=server_public_key,
                    obfuscation=obfuscation,
                ),
                "one_time": True,
            }

    def enroll_native_device(
        self,
        owner_id: object,
        *,
        name: object,
        platform: object,
        device_id: object,
        public_key: object,
        architecture: object,
        agent_version: object,
    ) -> dict[str, Any]:
        owner = _validated_owner(owner_id)
        device_name = _validated_name(name)
        device_platform = _validated_platform(platform)
        native_device_id = _validated_device_id(device_id)
        native_public_key = _validated_public_key(public_key)
        native_architecture = _validated_agent_field(architecture, "architecture")
        native_agent_version = _validated_agent_field(agent_version, "agent_version")
        with self._lock:
            devices = self._load()
            existing = next(
                (item for item in devices if item.get("id") == native_device_id),
                None,
            )
            if existing is not None:
                if (
                    existing.get("owner_id") != owner
                    or existing.get("public_key") != native_public_key
                    or existing.get("platform") != device_platform
                ):
                    raise DeviceError(409, "device_conflict", "Device identity conflict.")
                address = existing.get("address")
                preshared_key = existing.get("preshared_key")
                if not isinstance(address, str) or not _valid_key(preshared_key):
                    raise DeviceError(503, "invalid_state", "Stored device state is invalid.")
                return {
                    "device": self._public_device(existing, self._metrics()),
                    "provisioning": {
                        "schema_version": 1,
                        "device_id": native_device_id,
                        "address": address,
                        "preshared_key": preshared_key,
                    },
                    "one_time": True,
                    "idempotent_replay": True,
                }
            if sum(item.get("owner_id") == owner for item in devices) >= MAX_DEVICES_PER_OWNER:
                raise DeviceError(409, "device_limit_reached", "Device limit reached.")
            if any(item.get("public_key") == native_public_key for item in devices):
                raise DeviceError(409, "public_key_conflict", "Device public key conflict.")
            address = self._next_address(devices)
            preshared_key = self._generate_preshared_key()
            now = iso_utc()
            device = {
                "id": native_device_id,
                "owner_id": owner,
                "name": device_name,
                "platform": device_platform,
                "architecture": native_architecture,
                "agent_version": native_agent_version,
                "address": address,
                "public_key": native_public_key,
                "preshared_key": preshared_key,
                "enabled": True,
                "created_at": now,
                "updated_at": now,
            }
            self._apply_peer(native_public_key, preshared_key, address)
            try:
                self._save([*devices, device])
            except DeviceError:
                try:
                    self._remove_peer(native_public_key)
                except DeviceError:
                    LOGGER.error("failed to roll back newly enrolled native peer")
                raise
            return {
                "device": self._public_device(device, {}),
                "provisioning": {
                    "schema_version": 1,
                    "device_id": native_device_id,
                    "address": address,
                    "preshared_key": preshared_key,
                },
                "one_time": True,
                "idempotent_replay": False,
            }

    def set_device_enabled(
        self, owner_id: object, device_id: object, *, enabled: object
    ) -> dict[str, Any]:
        owner = _validated_owner(owner_id)
        if not isinstance(device_id, str) or DEVICE_ID_PATTERN.fullmatch(device_id) is None:
            raise DeviceError(404, "device_not_found", "Device not found.")
        if not isinstance(enabled, bool):
            raise DeviceError(400, "invalid_enabled", "Enabled must be a boolean.")
        with self._lock:
            devices = self._load()
            device = next(
                (
                    item
                    for item in devices
                    if item.get("id") == device_id and item.get("owner_id") == owner
                ),
                None,
            )
            if device is None:
                raise DeviceError(404, "device_not_found", "Device not found.")
            currently_enabled = device.get("enabled") is True
            if currently_enabled == enabled:
                return self._public_device(device, self._metrics())
            public_key = device.get("public_key")
            preshared_key = device.get("preshared_key")
            address = device.get("address")
            if not isinstance(public_key, str) or not isinstance(address, str):
                raise DeviceError(503, "invalid_state", "Stored device state is invalid.")
            if enabled:
                if not isinstance(preshared_key, str):
                    raise DeviceError(503, "invalid_state", "Stored device state is invalid.")
                self._apply_peer(public_key, preshared_key, address)
            else:
                self._remove_peer(public_key)
            device["enabled"] = enabled
            device["updated_at"] = iso_utc()
            try:
                self._save(devices)
            except DeviceError:
                try:
                    if currently_enabled and isinstance(preshared_key, str):
                        self._apply_peer(public_key, preshared_key, address)
                    elif not currently_enabled:
                        self._remove_peer(public_key)
                except DeviceError:
                    LOGGER.error("failed to roll back managed peer state")
                raise
            return self._public_device(device, self._metrics())

    def reconcile(self) -> None:
        with self._lock:
            devices = self._load()
            runtime_peers = self._runtime_peers()
            for device in devices:
                public_key = device.get("public_key")
                preshared_key = device.get("preshared_key")
                address = device.get("address")
                if (
                    device.get("enabled") is True
                    and isinstance(public_key, str)
                    and isinstance(preshared_key, str)
                    and isinstance(address, str)
                    and public_key not in runtime_peers
                ):
                    self._apply_peer(public_key, preshared_key, address)


def load_control_token(path: Path) -> str:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("control token unavailable") from exc
    if len(token) < 32 or len(token) > 256 or any(character.isspace() for character in token):
        raise RuntimeError("invalid control token")
    return token


def _credential_path(filename: str, fallback: Path) -> Path:
    credentials_directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if credentials_directory:
        return Path(credentials_directory) / filename
    return fallback


class AgentServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        manager: DeviceManager,
        control_token: str,
    ) -> None:
        super().__init__(server_address, handler)
        self.manager = manager
        self.control_token = control_token


class AgentHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "BarongVPNAgent"
    sys_version = ""

    @property
    def agent_server(self) -> AgentServer:
        return self.server  # type: ignore[return-value]

    def _send_json(self, status_code: int, payload: object, *, head_only: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _authorized_owner(self) -> str:
        expected = f"Bearer {self.agent_server.control_token}"
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, expected):
            raise DeviceError(401, "not_authenticated", "Not authenticated.")
        return _validated_owner(self.headers.get("X-Barong-User-ID"))

    def _read_json(self) -> dict[str, object]:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise DeviceError(415, "unsupported_media_type", "JSON body required.")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError as exc:
            raise DeviceError(400, "invalid_body", "Invalid request body.") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise DeviceError(400, "invalid_body", "Invalid request body.")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeviceError(400, "invalid_body", "Invalid request body.") from exc
        if not isinstance(payload, dict):
            raise DeviceError(400, "invalid_body", "Invalid request body.")
        return payload

    def _handle_device_error(self, error: DeviceError) -> None:
        self._send_json(
            error.status_code,
            {"error": error.code, "message": error.message},
        )

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "service": "barong-vpn-agent",
                    "version": VERSION,
                    "mode": "device_management",
                },
            )
            return
        if path == "/v1/status":
            payload = collect_status(self.agent_server.manager.command_runner)
            status_code = 200 if payload["status"] == "ok" else 503
            self._send_json(status_code, payload)
            return
        if path == "/v1/devices":
            try:
                owner = self._authorized_owner()
                devices = self.agent_server.manager.list_devices(owner)
            except DeviceError as exc:
                self._handle_device_error(exc)
                return
            self._send_json(200, {"devices": devices})
            return
        self._send_json(404, {"error": "not_found", "message": "Not found."})

    def do_HEAD(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path not in {"/health", "/v1/status"}:
            self._send_json(405, {"error": "method_not_allowed"}, head_only=True)
            return
        if path == "/health":
            self._send_json(200, {"status": "ok"}, head_only=True)
            return
        payload = collect_status(self.agent_server.manager.command_runner)
        self._send_json(200 if payload["status"] == "ok" else 503, payload, head_only=True)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path not in {"/v1/devices", "/v1/devices/enroll"}:
            self._send_json(405, {"error": "method_not_allowed"})
            return
        try:
            owner = self._authorized_owner()
            payload = self._read_json()
            if path == "/v1/devices/enroll":
                result = self.agent_server.manager.enroll_native_device(
                    owner,
                    name=payload.get("name"),
                    platform=payload.get("platform"),
                    device_id=payload.get("device_id"),
                    public_key=payload.get("public_key"),
                    architecture=payload.get("architecture"),
                    agent_version=payload.get("agent_version"),
                )
            else:
                result = self.agent_server.manager.create_device(
                    owner,
                    name=payload.get("name"),
                    platform=payload.get("platform"),
                )
        except DeviceError as exc:
            self._handle_device_error(exc)
            return
        self._send_json(201, result)

    def do_PATCH(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        prefix = "/v1/devices/"
        if not path.startswith(prefix):
            self._send_json(405, {"error": "method_not_allowed"})
            return
        try:
            owner = self._authorized_owner()
            payload = self._read_json()
            device = self.agent_server.manager.set_device_enabled(
                owner,
                path[len(prefix) :],
                enabled=payload.get("enabled"),
            )
        except DeviceError as exc:
            self._handle_device_error(exc)
            return
        self._send_json(200, {"device": device})

    def _method_not_allowed(self) -> None:
        self._send_json(405, {"error": "method_not_allowed"})

    do_PUT = _method_not_allowed
    do_DELETE = _method_not_allowed

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, POST, PATCH, OPTIONS")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        LOGGER.info("loopback request method=%s", self.command)


def reconcile_loop(manager: DeviceManager, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            manager.reconcile()
        except DeviceError:
            LOGGER.warning("managed peer reconciliation unavailable")
        stop_event.wait(RECONCILE_INTERVAL_SECONDS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Barong AmneziaWG device agent")
    parser.add_argument("--host", default=BIND_HOST)
    parser.add_argument("--port", type=int, default=BIND_PORT)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--dns", default=DEFAULT_DNS)
    parser.add_argument("--token-file", type=Path)
    args = parser.parse_args()
    if args.host != BIND_HOST:
        parser.error("the VPN agent must bind to 127.0.0.1")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    return args


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    token_path = args.token_file or _credential_path(
        "control-token", Path("/etc/barong-vpn-agent/control-token")
    )
    control_token = load_control_token(token_path)
    manager = DeviceManager(
        state_path=args.state_file,
        runtime_dir=args.runtime_dir,
        endpoint=args.endpoint,
        dns=args.dns,
    )
    stop_event = threading.Event()
    reconciler = threading.Thread(
        target=reconcile_loop,
        args=(manager, stop_event),
        name="managed-peer-reconciler",
        daemon=True,
    )
    reconciler.start()
    server = AgentServer(
        (args.host, args.port),
        AgentHandler,
        manager=manager,
        control_token=control_token,
    )
    LOGGER.info("barong-vpn-agent %s listening on loopback", VERSION)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.server_close()


if __name__ == "__main__":
    main()
