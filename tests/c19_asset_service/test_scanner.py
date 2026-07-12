from __future__ import annotations

import struct
from datetime import UTC, datetime, timedelta

import pytest

from c19_asset_service.scanner import (
    ClamdScanner,
    MalwareDetectedError,
    ScannerUnavailableError,
)


class FakeSocket:
    def __init__(self, response: bytes):
        self.response = response
        self.sent = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def settimeout(self, value):
        assert value > 0

    def sendall(self, value):
        self.sent.extend(value)

    def recv(self, size):
        del size
        response, self.response = self.response, b""
        return response


def test_clamd_instream_protocol_and_clean_response(tmp_path, monkeypatch):
    source = tmp_path / "sample.bin"
    source.write_bytes(b"abcdef")
    now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    version = FakeSocket(b"ClamAV 1.4.5/28000/Sat Jul 11 11:30:00 2026\0")
    connection = FakeSocket(b"stream: OK\0")
    connections = iter((version, connection))
    monkeypatch.setattr(
        "c19_asset_service.scanner.socket.create_connection",
        lambda address, timeout: next(connections),
    )
    ClamdScanner("clamd", chunk_size=3, now_provider=lambda: now).scan(source)
    assert bytes(version.sent) == b"zVERSION\0"
    sent = bytes(connection.sent)
    assert sent.startswith(b"zINSTREAM\0")
    payload = sent[len(b"zINSTREAM\0") :]
    assert payload == (
        struct.pack("!I", 3)
        + b"abc"
        + struct.pack("!I", 3)
        + b"def"
        + struct.pack("!I", 0)
    )


def test_clamd_malware_and_failure_are_fail_closed(tmp_path, monkeypatch):
    source = tmp_path / "sample.bin"
    source.write_bytes(b"test")
    now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    fresh = b"ClamAV 1.4.5/28000/Sat Jul 11 11:30:00 2026\0"
    infected = iter(
        (FakeSocket(fresh), FakeSocket(b"stream: Eicar-Test-Signature FOUND\0"))
    )
    monkeypatch.setattr(
        "c19_asset_service.scanner.socket.create_connection",
        lambda address, timeout: next(infected),
    )
    with pytest.raises(MalwareDetectedError):
        ClamdScanner("clamd", now_provider=lambda: now).scan(source)
    invalid = iter((FakeSocket(fresh), FakeSocket(b"unexpected\0")))
    monkeypatch.setattr(
        "c19_asset_service.scanner.socket.create_connection",
        lambda address, timeout: next(invalid),
    )
    with pytest.raises(ScannerUnavailableError):
        ClamdScanner("clamd", now_provider=lambda: now).scan(source)
    monkeypatch.setattr(
        "c19_asset_service.scanner.socket.create_connection",
        lambda address, timeout: (_ for _ in ()).throw(OSError("offline")),
    )
    with pytest.raises(ScannerUnavailableError):
        ClamdScanner("clamd", now_provider=lambda: now).scan(source)


def test_stale_unparseable_and_future_signature_databases_fail_closed(
    tmp_path, monkeypatch
):
    source = tmp_path / "sample.bin"
    source.write_bytes(b"test")
    now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    for response in (
        b"ClamAV 1.4.5/27000/Wed Jul 08 10:00:00 2026\0",
        b"ClamAV invalid-version-response\0",
        b"ClamAV 1.4.5/29000/Sat Jul 11 13:00:00 2026\0",
    ):
        connection = FakeSocket(response)
        monkeypatch.setattr(
            "c19_asset_service.scanner.socket.create_connection",
            lambda address, timeout, value=connection: value,
        )
        with pytest.raises(ScannerUnavailableError):
            ClamdScanner(
                "clamd",
                signature_max_age_hours=48,
                now_provider=lambda: now,
            ).scan(source)
