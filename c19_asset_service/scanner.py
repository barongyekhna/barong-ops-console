"""Minimal ClamAV INSTREAM client with fail-closed error semantics."""

from __future__ import annotations

import socket
import struct
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Protocol


class ScanError(RuntimeError):
    pass


class ScannerUnavailableError(ScanError):
    pass


class MalwareDetectedError(ScanError):
    pass


class Scanner(Protocol):
    def scan(self, path: Path) -> None: ...


class ClamdScanner:
    def __init__(
        self,
        host: str,
        port: int = 3310,
        *,
        timeout_seconds: float = 600.0,
        chunk_size: int = 1024 * 1024,
        signature_max_age_hours: int = 48,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            not host
            or port <= 0
            or timeout_seconds <= 0
            or chunk_size <= 0
            or signature_max_age_hours <= 0
        ):
            raise ValueError("invalid scanner configuration")
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.chunk_size = chunk_size
        self.signature_max_age_hours = signature_max_age_hours
        self.now_provider = now_provider or (lambda: datetime.now(UTC))

    def _connection(self):
        connection = socket.create_connection(
            (self.host, self.port), timeout=self.timeout_seconds
        )
        connection.settimeout(self.timeout_seconds)
        return connection

    @staticmethod
    def _receive(connection: socket.socket) -> bytes:
        response = bytearray()
        while len(response) <= 4096:
            block = connection.recv(1024)
            if not block:
                break
            response.extend(block)
            if b"\0" in block or b"\n" in block:
                break
        if len(response) > 4096:
            raise ScannerUnavailableError("malware scanner response is too large")
        return bytes(response).rstrip(b"\0\r\n")

    def _assert_fresh_signatures(self) -> None:
        try:
            with self._connection() as connection:
                connection.sendall(b"zVERSION\0")
                response = self._receive(connection).decode("ascii", errors="strict")
            date_text = response.rsplit("/", 1)[1].strip()
            try:
                signature_time = parsedate_to_datetime(date_text)
            except (TypeError, ValueError):
                signature_time = datetime.strptime(
                    date_text, "%a %b %d %H:%M:%S %Y"
                )
            if signature_time.tzinfo is None:
                signature_time = signature_time.replace(tzinfo=UTC)
            else:
                signature_time = signature_time.astimezone(UTC)
            now = self.now_provider().astimezone(UTC)
            if (
                signature_time > now + timedelta(minutes=15)
                or now - signature_time
                > timedelta(hours=self.signature_max_age_hours)
            ):
                raise ScannerUnavailableError("malware signatures are not fresh")
        except ScannerUnavailableError:
            raise
        except (OSError, TimeoutError, UnicodeError, IndexError, ValueError) as exc:
            raise ScannerUnavailableError(
                "malware signature freshness could not be verified"
            ) from exc

    def scan(self, path: Path) -> None:
        self._assert_fresh_signatures()
        try:
            with self._connection() as connection:
                connection.sendall(b"zINSTREAM\0")
                with path.open("rb") as handle:
                    while True:
                        block = handle.read(self.chunk_size)
                        if not block:
                            break
                        connection.sendall(struct.pack("!I", len(block)))
                        connection.sendall(block)
                connection.sendall(struct.pack("!I", 0))
                response = self._receive(connection)
        except MalwareDetectedError:
            raise
        except (OSError, TimeoutError) as exc:
            raise ScannerUnavailableError("malware scanner unavailable") from exc
        normalized = response
        if normalized.endswith(b" OK"):
            return
        if normalized.endswith(b" FOUND"):
            raise MalwareDetectedError("malware detected")
        raise ScannerUnavailableError("malware scanner returned an invalid response")
