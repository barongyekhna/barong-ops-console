from __future__ import annotations

import hashlib
from pathlib import Path

from c19_asset_service.config import GatewaySettings
from c19_asset_service.gateway import GatewayControlError, create_gateway_app
from c19_asset_service.schemas import (
    GatewayDownloadAuthorizeResponse,
    GatewayUploadAuthorizeResponse,
)
from c19_asset_asgi_client import ASGIClient


TICKET = "A" * 43


class FakeControl:
    def __init__(self, *, upload_key="aa/bb/cc", download=None):
        self.upload_key = upload_key
        self.download = download
        self.completions: list[tuple[str, int, str]] = []
        self.upload_calls = 0
        self.download_calls = 0
        self.closed = False

    async def authorize_upload(self, ticket, content_length):
        self.upload_calls += 1
        if ticket != TICKET:
            raise GatewayControlError("denied")
        return GatewayUploadAuthorizeResponse(
            asset_id="att_" + "a" * 32,
            object_key=self.upload_key,
            expected_size_bytes=5,
            maximum_size_bytes=10,
            upload_state="ready",
        )

    async def complete_upload(self, ticket, size_bytes, sha256_hex):
        self.completions.append((ticket, size_bytes, sha256_hex))

    async def authorize_download(self, ticket, method):
        self.download_calls += 1
        if ticket != TICKET or self.download is None:
            raise GatewayControlError("denied")
        return self.download

    async def close(self):
        self.closed = True


def _settings(tmp_path):
    incoming = tmp_path / "incoming"
    active = tmp_path / "active"
    active.mkdir()
    return GatewaySettings(
        api_url="http://asset-api:8091",
        gateway_token="g" * 32,
        incoming_root=incoming,
        active_root=active,
    )


def test_exact_public_path_streams_and_hashes_upload(tmp_path):
    settings = _settings(tmp_path)
    control = FakeControl()
    app = create_gateway_app(settings, control=control)
    with ASGIClient(app) as client:
        response = client.put(
            f"/api/backend/c19-assets/u/{TICKET}",
            content=b"hello",
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 202
        assert response.json() == {"status": "uploaded"}
        assert client.put(f"/u/{TICKET}", content=b"hello").status_code == 404
        assert (
            client.put(f"/api/c19-assets/u/{TICKET}", content=b"hello").status_code
            == 404
        )
    stored = settings.incoming_root / control.upload_key
    assert stored.read_bytes() == b"hello"
    assert control.completions == [
        (TICKET, 5, hashlib.sha256(b"hello").hexdigest())
    ]


def test_gateway_rejects_malformed_ticket_paths_before_control_calls(tmp_path):
    settings = _settings(tmp_path)
    control = FakeControl()
    app = create_gateway_app(settings, control=control)
    with ASGIClient(app) as client:
        for ticket in ("A" * 42, "A" * 44, "." * 43, "A" * 42 + "!"):
            assert (
                client.put(
                    f"/api/backend/c19-assets/u/{ticket}",
                    content=b"hello",
                ).status_code
                == 404
            )
            assert (
                client.get(f"/api/backend/c19-assets/d/{ticket}").status_code
                == 404
            )
    assert control.upload_calls == 0
    assert control.download_calls == 0


def test_stream_limit_removes_partial_file(tmp_path):
    settings = _settings(tmp_path)
    control = FakeControl()
    app = create_gateway_app(settings, control=control)
    with ASGIClient(app) as client:
        response = client.put(f"/api/backend/c19-assets/u/{TICKET}", content=b"123456")
    assert response.status_code == 413
    assert not (settings.incoming_root / control.upload_key).exists()
    assert not list(settings.incoming_root.rglob("*.part"))
    assert not control.completions


def test_existing_durable_object_retries_only_completion(tmp_path):
    settings = _settings(tmp_path)
    control = FakeControl()
    stored = settings.incoming_root / control.upload_key
    stored.parent.mkdir(parents=True)
    stored.write_bytes(b"hello")
    app = create_gateway_app(settings, control=control)
    with ASGIClient(app) as client:
        response = client.put(f"/api/backend/c19-assets/u/{TICKET}", content=b"hello")
    assert response.status_code == 202
    assert stored.read_bytes() == b"hello"
    assert control.completions == [
        (TICKET, 5, hashlib.sha256(b"hello").hexdigest())
    ]


def test_stale_partial_from_crashed_process_does_not_block_retry(tmp_path):
    settings = _settings(tmp_path)
    control = FakeControl()
    target = settings.incoming_root / control.upload_key
    target.parent.mkdir(parents=True)
    stale = target.with_name(f".{target.name}.stale.part")
    stale.write_bytes(b"incomplete")
    app = create_gateway_app(settings, control=control)
    with ASGIClient(app) as client:
        response = client.put(f"/api/backend/c19-assets/u/{TICKET}", content=b"hello")
    assert response.status_code == 202
    assert target.read_bytes() == b"hello"
    assert stale.read_bytes() == b"incomplete"


def test_completed_authorization_does_not_create_another_object(tmp_path):
    settings = _settings(tmp_path)

    class CompletedControl(FakeControl):
        async def authorize_upload(self, ticket, content_length):
            return GatewayUploadAuthorizeResponse(
                asset_id="att_" + "a" * 32,
                object_key=None,
                expected_size_bytes=5,
                maximum_size_bytes=10,
                upload_state="completed",
            )

    control = CompletedControl()
    app = create_gateway_app(settings, control=control)
    with ASGIClient(app) as client:
        response = client.put(f"/api/backend/c19-assets/u/{TICKET}", content=b"hello")
    assert response.status_code == 202
    assert not list(settings.incoming_root.rglob("*"))
    assert not control.completions


def _download_control(settings, content=b"0123456789"):
    key = "dd/ee/ff"
    path = settings.active_root / key
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    metadata = GatewayDownloadAuthorizeResponse(
        asset_id="att_" + "b" * 32,
        object_key=key,
        filename='财务 "Q4".pdf',
        media_type="application/pdf",
        size_bytes=len(content),
        sha256_hex=hashlib.sha256(content).hexdigest(),
        disposition="attachment",
        variant="original",
    )
    return FakeControl(download=metadata)


def test_download_headers_head_and_single_ranges(tmp_path):
    settings = _settings(tmp_path)
    control = _download_control(settings)
    app = create_gateway_app(settings, control=control)
    with ASGIClient(app) as client:
        full = client.get(f"/api/backend/c19-assets/d/{TICKET}")
        assert full.status_code == 200
        assert full.content == b"0123456789"
        assert full.headers["cache-control"] == "private, no-store"
        assert full.headers["x-content-type-options"] == "nosniff"
        assert full.headers["referrer-policy"] == "no-referrer"
        assert full.headers["content-type"].startswith("application/pdf")
        disposition = full.headers["content-disposition"]
        assert disposition.startswith("attachment; filename=download;")
        assert "%22" in disposition and "财务" not in disposition
        ranged = client.get(
            f"/api/backend/c19-assets/d/{TICKET}", headers={"Range": "bytes=2-5"}
        )
        assert ranged.status_code == 206
        assert ranged.content == b"2345"
        assert ranged.headers["content-range"] == "bytes 2-5/10"
        suffix = client.get(
            f"/api/backend/c19-assets/d/{TICKET}", headers={"Range": "bytes=-3"}
        )
        assert suffix.status_code == 206
        assert suffix.content == b"789"
        head = client.head(
            f"/api/backend/c19-assets/d/{TICKET}", headers={"Range": "bytes=1-3"}
        )
        assert head.status_code == 206
        assert head.content == b""
        assert head.headers["content-length"] == "3"
        assert head.headers["content-range"] == "bytes 1-3/10"


def test_multipart_and_unsatisfiable_ranges_return_416(tmp_path):
    settings = _settings(tmp_path)
    app = create_gateway_app(settings, control=_download_control(settings))
    with ASGIClient(app) as client:
        for value in ("bytes=0-1,3-4", "bytes=99-", "items=0-1", "bytes=-0"):
            response = client.get(
                f"/api/backend/c19-assets/d/{TICKET}", headers={"Range": value}
            )
            assert response.status_code == 416
            assert response.headers["content-range"] == "bytes */10"
            assert response.headers["cache-control"] == "private, no-store"


def test_missing_or_size_changed_object_is_hidden(tmp_path):
    settings = _settings(tmp_path)
    control = _download_control(settings)
    path = settings.active_root / control.download.object_key
    path.write_bytes(b"changed")
    app = create_gateway_app(settings, control=control)
    with ASGIClient(app) as client:
        response = client.get(f"/api/backend/c19-assets/d/{TICKET}")
    assert response.status_code == 404
    assert control.download.object_key not in response.text
