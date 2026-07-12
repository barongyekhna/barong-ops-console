from __future__ import annotations

import hashlib
import os
import threading
from datetime import UTC, datetime, timedelta

from c19_asset_service.config import WorkerSettings
from c19_asset_service.models import Asset
from c19_asset_service.scanner import MalwareDetectedError, ScannerUnavailableError
from c19_asset_service.worker import AssetWorker

from c19_asset_test_helpers import moment_upload_payload, upload_payload


class CleanScanner:
    def __init__(self):
        self.paths = []

    def scan(self, path):
        self.paths.append(path)


class OfflineScanner:
    def scan(self, path):
        del path
        raise ScannerUnavailableError("offline")


class InfectedScanner:
    def scan(self, path):
        del path
        raise MalwareDetectedError("infected")


def _settings(api_settings, tmp_path):
    return WorkerSettings(
        database_url=api_settings.database_url,
        dataset_id=api_settings.dataset_id,
        incoming_root=tmp_path / "incoming",
        active_root=tmp_path / "active",
        quarantine_root=tmp_path / "quarantine",
        clamd_host="fake-clamd",
        poll_seconds=1,
    )


def _store_upload(client, service_headers, gateway_headers, settings, body, **kwargs):
    payload = upload_payload(body, **kwargs)
    intent = client.post(
        "/v1/upload-intents", headers=service_headers, json=payload
    )
    assert intent.status_code == 201, intent.text
    result = intent.json()
    ticket = result["upload_ticket"]
    authorized = client.post(
        "/internal/uploads/authorize",
        headers=gateway_headers,
        json={"ticket": ticket, "method": "PUT", "content_length": len(body)},
    )
    assert authorized.status_code == 200, authorized.text
    object_path = settings.incoming_root / authorized.json()["object_key"]
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_bytes(body)
    completed = client.post(
        "/internal/uploads/complete",
        headers=gateway_headers,
        json={
            "ticket": ticket,
            "size_bytes": len(body),
            "sha256_hex": hashlib.sha256(body).hexdigest(),
        },
    )
    assert completed.status_code == 200, completed.text
    return result["asset"]["asset_id"], payload


def _store_moment_upload(
    client, service_headers, gateway_headers, settings, body, **kwargs
):
    payload = moment_upload_payload(body, **kwargs)
    intent = client.post(
        "/v1/moment-assets/upload-intents",
        headers=service_headers,
        json=payload,
    )
    assert intent.status_code == 201, intent.text
    result = intent.json()
    ticket = result["upload_ticket"]
    authorized = client.post(
        "/internal/uploads/authorize",
        headers=gateway_headers,
        json={"ticket": ticket, "method": "PUT", "content_length": len(body)},
    )
    assert authorized.status_code == 200, authorized.text
    object_path = settings.incoming_root / authorized.json()["object_key"]
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_bytes(body)
    completed = client.post(
        "/internal/uploads/complete",
        headers=gateway_headers,
        json={
            "ticket": ticket,
            "size_bytes": len(body),
            "sha256_hex": hashlib.sha256(body).hexdigest(),
        },
    )
    assert completed.status_code == 200, completed.text
    return result["asset"]["asset_id"], payload


def test_worker_promotes_binds_downloads_and_permanently_tombstones(
    client,
    app,
    api_settings,
    service_headers,
    gateway_headers,
    tmp_path,
):
    settings = _settings(api_settings, tmp_path)
    body = b"plain business document\n"
    asset_id, payload = _store_upload(
        client, service_headers, gateway_headers, settings, body
    )
    scanner = CleanScanner()
    worker = AssetWorker(settings, scanner=scanner)
    try:
        assert worker.run_once() is True
        assert worker.run_once() is False
        with app.state.database.session_factory() as session:
            asset = session.get(Asset, asset_id)
            assert asset is not None
            assert asset.status == "active"
            assert asset.active_object_key
            assert asset.incoming_object_key is None
            active_path = settings.active_root / asset.active_object_key
            assert active_path.read_bytes() == body
            assert asset.actual_sha256_hex == hashlib.sha256(body).hexdigest()
        assert scanner.paths
        prepared = client.post(
            f"/v1/assets/{asset_id}/bindings/prepare",
            headers=service_headers,
            json={
                "owner_user_id": "user-1",
                "conversation_id": "conversation-1",
                "client_message_id": "message-1",
            },
        )
        assert prepared.status_code == 200
        committed = client.post(
            f"/v1/assets/{asset_id}/bindings/commit",
            headers=service_headers,
            json={
                "owner_user_id": "user-1",
                "conversation_id": "conversation-1",
                "client_message_id": "message-1",
                "record_id": "record-1",
            },
        )
        assert committed.status_code == 200
        download = client.post(
            f"/v1/assets/{asset_id}/download-intents",
            headers=service_headers,
            json={
                "owner_user_id": "user-1",
                "reader_user_id": "reader-1",
                "conversation_id": "conversation-1",
                "record_id": "record-1",
                "variant": "original",
                "disposition": "attachment",
                "asset_version": 1,
            },
        )
        assert download.status_code == 201
        authorized = client.post(
            "/internal/downloads/authorize",
            headers=gateway_headers,
            json={
                "ticket": download.json()["download_ticket"],
                "method": "GET",
            },
        )
        assert authorized.status_code == 200
        assert authorized.json()["sha256_hex"] == hashlib.sha256(body).hexdigest()
        delete = client.post(
            f"/v1/assets/{asset_id}/delete",
            headers=service_headers,
            json={
                "requested_by_user_id": "user-1",
                "reason": "user requested deletion",
                "requested_at": payload["requested_at"],
            },
        )
        assert delete.status_code == 200
        assert delete.json()["status"] == "delete_pending"
        assert worker.run_once() is True
        with app.state.database.session_factory() as session:
            tombstone = session.get(Asset, asset_id)
            assert tombstone is not None
            assert tombstone.status == "deleted"
            assert tombstone.intent_sha256 is None
            assert tombstone.filename is None
            assert tombstone.media_type is None
            assert tombstone.declared_sha256_hex is None
            assert tombstone.actual_sha256_hex is None
            assert tombstone.active_object_key is None
            assert tombstone.incoming_object_key is None
            assert tombstone.quarantine_object_key is None
        assert not active_path.exists()
        replay = client.post(
            "/v1/upload-intents", headers=service_headers, json=payload
        )
        assert replay.status_code == 410
    finally:
        worker.close()


def test_worker_generates_only_safe_image_thumbnail(
    client,
    app,
    api_settings,
    service_headers,
    gateway_headers,
    tmp_path,
):
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (800, 600), (10, 20, 30)).save(output, format="JPEG", exif=b"Exif\x00\x00")
    body = output.getvalue()
    settings = _settings(api_settings, tmp_path)
    asset_id, _ = _store_upload(
        client,
        service_headers,
        gateway_headers,
        settings,
        body,
        client_asset_id="image-asset-1",
        filename="photo.jpg",
        media_type="image/jpeg",
        kind="image",
    )
    worker = AssetWorker(settings, scanner=CleanScanner())
    try:
        assert worker.run_once() is True
        with app.state.database.session_factory() as session:
            asset = session.get(Asset, asset_id)
            assert asset is not None and asset.status == "active"
            assert asset.thumbnail_object_key
            thumbnail = settings.active_root / asset.thumbnail_object_key
            with Image.open(thumbnail) as image:
                assert image.format == "PNG"
                assert image.width <= 512 and image.height <= 512
                assert not image.getexif()
            assert asset.thumbnail_media_type == "image/png"
            assert asset.thumbnail_sha256_hex == hashlib.sha256(
                thumbnail.read_bytes()
            ).hexdigest()
    finally:
        worker.close()


def test_worker_promotes_and_tombstones_moment_image_without_chat_scope(
    client,
    app,
    api_settings,
    service_headers,
    gateway_headers,
    tmp_path,
):
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (32, 24), (90, 40, 10)).save(output, format="PNG")
    body = output.getvalue()
    settings = _settings(api_settings, tmp_path)
    moment_id = "mom_" + "a" * 32
    asset_id, payload = _store_moment_upload(
        client,
        service_headers,
        gateway_headers,
        settings,
        body,
        client_asset_id="moment-worker-image",
        scope_id=moment_id,
    )
    worker = AssetWorker(settings, scanner=CleanScanner())
    try:
        assert worker.run_once() is True
        with app.state.database.session_factory() as session:
            asset = session.get(Asset, asset_id)
            assert asset is not None
            assert asset.status == "active"
            assert asset.usage == "moment_image"
            assert asset.scope_id == moment_id
            assert asset.conversation_id is None
            assert asset.thumbnail_object_key
            active_path = settings.active_root / str(asset.active_object_key)
            thumbnail_path = settings.active_root / str(asset.thumbnail_object_key)
            assert active_path.read_bytes() == body
            assert thumbnail_path.is_file()

        prepare = {
            "owner_user_id": "user-1",
            "scope_id": moment_id,
            "binding_client_id": "client-moment-worker",
        }
        assert client.post(
            f"/v1/moment-assets/{asset_id}/bindings/prepare",
            headers=service_headers,
            json=prepare,
        ).status_code == 200
        assert client.post(
            f"/v1/moment-assets/{asset_id}/bindings/commit",
            headers=service_headers,
            json={**prepare, "bound_resource_id": moment_id},
        ).status_code == 200
        ticket = client.post(
            f"/v1/moment-assets/{asset_id}/download-intents",
            headers=service_headers,
            json={
                "owner_user_id": "user-1",
                "reader_user_id": "reader-1",
                "scope_id": moment_id,
                "bound_resource_id": moment_id,
                "variant": "thumbnail",
                "disposition": "inline",
                "asset_version": 1,
            },
        )
        assert ticket.status_code == 201
        assert client.post(
            "/internal/downloads/authorize",
            headers=gateway_headers,
            json={"ticket": ticket.json()["download_ticket"], "method": "GET"},
        ).status_code == 200

        deletion = client.post(
            f"/v1/assets/{asset_id}/delete",
            headers=service_headers,
            json={
                "requested_by_user_id": "user-1",
                "reason": "Moment deleted",
                "requested_at": payload["requested_at"],
            },
        )
        assert deletion.status_code == 200
        assert worker.run_once() is True
        with app.state.database.session_factory() as session:
            asset = session.get(Asset, asset_id)
            assert asset is not None
            assert asset.status == "deleted"
            assert asset.usage == "moment_image"
            assert asset.scope_id == moment_id
            assert asset.filename is None
        assert not active_path.exists()
        assert not thumbnail_path.exists()
    finally:
        worker.close()


def test_scanner_failure_and_malware_are_never_promoted(
    client,
    app,
    api_settings,
    service_headers,
    gateway_headers,
    tmp_path,
):
    for index, scanner, failure in (
        (1, OfflineScanner(), "scanner_unavailable"),
        (2, InfectedScanner(), "malware_detected"),
    ):
        settings = _settings(api_settings, tmp_path)
        asset_id, _ = _store_upload(
            client,
            service_headers,
            gateway_headers,
            settings,
            f"sample {index}\n".encode(),
            client_asset_id=f"scan-failure-{index}",
        )
        worker = AssetWorker(settings, scanner=scanner)
        try:
            assert worker.run_once() is True
        finally:
            worker.close()
        with app.state.database.session_factory() as session:
            asset = session.get(Asset, asset_id)
            assert asset is not None
            assert asset.status == "quarantined"
            assert asset.failure_code == failure
            assert asset.active_object_key is None
            assert asset.quarantine_object_key
            quarantined = settings.quarantine_root / asset.quarantine_object_key
            assert quarantined.is_file()


def test_manual_quarantine_immediately_invalidates_active_download(
    client,
    app,
    api_settings,
    service_headers,
    gateway_headers,
    tmp_path,
):
    settings = _settings(api_settings, tmp_path)
    asset_id, payload = _store_upload(
        client,
        service_headers,
        gateway_headers,
        settings,
        b"quarantine me\n",
        client_asset_id="manual-quarantine",
    )
    worker = AssetWorker(settings, scanner=CleanScanner())
    try:
        assert worker.run_once() is True
        response = client.post(
            f"/v1/assets/{asset_id}/quarantine",
            headers=service_headers,
            json={
                "requested_by_user_id": "security-operator",
                "reason": "security review",
                "requested_at": payload["requested_at"],
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "quarantined"
        assert worker.run_once() is True
        with app.state.database.session_factory() as session:
            asset = session.get(Asset, asset_id)
            assert asset is not None
            assert asset.active_object_key is None
            assert asset.quarantine_object_key
            assert (settings.quarantine_root / asset.quarantine_object_key).is_file()
    finally:
        worker.close()


def test_unbound_active_asset_expires_and_orphan_files_are_reclaimed(
    client,
    app,
    api_settings,
    service_headers,
    gateway_headers,
    tmp_path,
):
    settings = _settings(api_settings, tmp_path)
    asset_id, payload = _store_upload(
        client,
        service_headers,
        gateway_headers,
        settings,
        b"never attached\n",
        client_asset_id="abandoned-unbound",
    )
    worker = AssetWorker(settings, scanner=CleanScanner())
    try:
        assert worker.run_once() is True
        with app.state.database.session_factory() as session:
            asset = session.get(Asset, asset_id)
            assert asset is not None and asset.active_object_key
            active_path = settings.active_root / asset.active_object_key
            asset.activated_at = datetime.now(UTC) - timedelta(
                hours=settings.unbound_asset_ttl_hours + 1
            )
            asset.updated_at = asset.activated_at
            session.commit()
        orphan_key = "aa/bb/" + "c" * 28
        orphan = settings.active_root / orphan_key
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(b"promotion orphan")
        old = (
            datetime.now(UTC) - timedelta(hours=settings.orphan_grace_hours + 1)
        ).timestamp()
        os.utime(orphan, (old, old))
        stale_partial = settings.incoming_root / "dd" / "ee" / (
            "." + "f" * 28 + "." + "a" * 32 + ".part"
        )
        stale_partial.parent.mkdir(parents=True, exist_ok=True)
        stale_partial.write_bytes(b"crashed stream")
        os.utime(stale_partial, (old, old))
        stale_thumbnail = settings.incoming_root / ".worker" / (
            "b" * 32 + ".png"
        )
        stale_thumbnail.parent.mkdir(parents=True, exist_ok=True)
        stale_thumbnail.write_bytes(b"crashed thumbnail")
        os.utime(stale_thumbnail, (old, old))
        worker._last_orphan_cleanup = None
        assert worker.run_once() is True
        with app.state.database.session_factory() as session:
            asset = session.get(Asset, asset_id)
            assert asset is not None
            assert asset.status == "deleted"
            assert asset.filename is None
        assert not active_path.exists()
        assert not orphan.exists()
        assert not stale_partial.exists()
        assert not stale_thumbnail.exists()
        replay = client.post(
            "/v1/upload-intents", headers=service_headers, json=payload
        )
        assert replay.status_code == 410
    finally:
        worker.close()


def test_worker_shutdown_finishes_current_run_once_before_exit(
    client, api_settings, tmp_path
):
    del client  # Fixture initializes and later disposes the shared test schema.
    settings = _settings(api_settings, tmp_path)
    worker = AssetWorker(settings, scanner=CleanScanner())
    shutdown = threading.Event()
    calls: list[str] = []

    def current_unit_of_work() -> bool:
        calls.append("started")
        # This models SIGTERM arriving while a DB/filesystem transition owns the
        # worker thread. The method still reaches its normal return boundary.
        shutdown.set()
        calls.append("completed")
        return True

    worker.run_once = current_unit_of_work  # type: ignore[method-assign]
    try:
        worker.run_forever(stop_event=shutdown)
    finally:
        worker.close()

    assert calls == ["started", "completed"]
