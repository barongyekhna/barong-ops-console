from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from c19_asset_service.api import create_api_app
from c19_asset_service.models import Asset, AssetAuditEvent, TransferTicket
from c19_asset_service.repository import _dataset_quota_lock_statement
from c19_asset_service.validation import (
    ContentValidationError,
    ValidationLimits,
    validate_content,
)
from c19_asset_asgi_client import ASGIClient
from c19_asset_test_helpers import upload_payload


def _client_for(api_settings, **limits):
    settings = replace(api_settings, **limits)
    app = create_api_app(settings, create_schema=True)
    return app, ASGIClient(app)


def _close(app) -> None:
    app.state.database_executor.shutdown(wait=True, cancel_futures=True)
    app.state.database.dispose()


def _intent(
    client,
    headers,
    *,
    owner="user-1",
    client_id="asset-1",
    size=100,
    kind="file",
):
    payload = upload_payload(
        b"x" * size,
        client_asset_id=client_id,
        kind=kind,
        filename="image.png" if kind == "image" else "notes.txt",
        media_type="image/png" if kind == "image" else "text/plain",
    )
    payload["owner_user_id"] = owner
    return client.post("/v1/upload-intents", headers=headers, json=payload)


def test_owner_and_global_reserved_file_quotas_are_durable(
    api_settings, service_headers
) -> None:
    app, client = _client_for(
        api_settings,
        owner_reserved_file_limit=2,
        owner_reserved_byte_limit=10_000,
        global_reserved_file_limit=3,
        global_reserved_byte_limit=20_000,
        thumbnail_max_bytes=100,
    )
    try:
        assert _intent(client, service_headers, client_id="u1-1").status_code == 201
        assert _intent(client, service_headers, client_id="u1-2").status_code == 201
        owner_rejected = _intent(client, service_headers, client_id="u1-3")
        assert owner_rejected.status_code == 429
        assert owner_rejected.json() == {"detail": "asset quota exceeded"}
        assert (
            _intent(
                client,
                service_headers,
                owner="user-2",
                client_id="u2-1",
            ).status_code
            == 201
        )
        global_rejected = _intent(
            client,
            service_headers,
            owner="user-3",
            client_id="u3-1",
        )
        assert global_rejected.status_code == 429
        with app.state.database.session_factory() as session:
            assert session.scalar(select(func.count(Asset.asset_id))) == 3
    finally:
        _close(app)


def test_reserved_bytes_include_thumbnail_and_delete_pending_until_tombstoned(
    api_settings, service_headers
) -> None:
    app, client = _client_for(
        api_settings,
        owner_reserved_file_limit=10,
        owner_reserved_byte_limit=180,
        global_reserved_file_limit=20,
        global_reserved_byte_limit=1000,
        thumbnail_max_bytes=50,
    )
    try:
        created = _intent(
            client,
            service_headers,
            client_id="with-thumb",
            size=100,
            kind="image",
        )
        assert created.status_code == 201
        asset_id = created.json()["asset"]["asset_id"]
        with app.state.database.session_factory() as session:
            asset = session.get(Asset, asset_id)
            assert asset is not None
            asset.status = "delete_pending"
            asset.actual_size_bytes = 100
            asset.actual_sha256_hex = asset.declared_sha256_hex
            asset.thumbnail_size_bytes = 50
            asset.thumbnail_sha256_hex = "a" * 64
            asset.thumbnail_media_type = "image/jpeg"
            asset.thumbnail_object_key = "aa/bb/thumb"
            session.commit()
        snapshot = client.get("/v1/ops/snapshot", headers=service_headers).json()
        assert snapshot["reserved_asset_files"] == 1
        assert snapshot["reserved_asset_bytes"] == 150
        rejected = _intent(
            client,
            service_headers,
            client_id="over-with-thumb",
            size=31,
            kind="image",
        )
        assert rejected.status_code == 429

        # Capacity is released only after the byte-owning worker has reached
        # the permanent body-free tombstone, never merely on delete request.
        with app.state.database.session_factory() as session:
            asset = session.get(Asset, asset_id)
            assert asset is not None
            asset.status = "deleted"
            asset.intent_sha256 = None
            asset.filename = None
            asset.media_type = None
            asset.declared_size_bytes = None
            asset.declared_sha256_hex = None
            asset.actual_size_bytes = None
            asset.actual_sha256_hex = None
            asset.incoming_object_key = None
            asset.active_object_key = None
            asset.quarantine_object_key = None
            asset.thumbnail_object_key = None
            asset.thumbnail_size_bytes = None
            asset.thumbnail_sha256_hex = None
            asset.thumbnail_media_type = None
            asset.deleted_at = datetime.now(UTC)
            session.commit()
        assert (
            _intent(
                client,
                service_headers,
                client_id="after-delete",
                size=100,
                kind="image",
            ).status_code
            == 201
        )
    finally:
        _close(app)


def test_quota_check_uses_postgres_dataset_row_lock() -> None:
    sql = str(
        _dataset_quota_lock_statement().compile(dialect=postgresql.dialect())
    )
    assert "asset_dataset_identity" in sql
    assert sql.rstrip().endswith("FOR UPDATE")


def test_exact_chat_retention_handoff_protects_mismatch_and_is_idempotent(
    client, app, service_headers
) -> None:
    created = _intent(client, service_headers, client_id="retention-asset")
    assert created.status_code == 201
    body = created.json()
    asset_id = body["asset"]["asset_id"]
    record_id = str(uuid.uuid4())
    operation_id = str(uuid.uuid4())
    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        asset.status = "active"
        asset.actual_size_bytes = asset.declared_size_bytes
        asset.actual_sha256_hex = asset.declared_sha256_hex
        asset.active_object_key = "aa/bb/active"
        asset.incoming_object_key = None
        asset.binding_status = "committed"
        asset.binding_client_id = "client-message-1"
        asset.bound_resource_id = record_id
        asset.committed_at = datetime.now(UTC)
        session.commit()

    payload = {
        "operation_id": operation_id,
        "record_id": str(uuid.uuid4()),
        "conversation_id": "conversation-1",
        "requested_at": datetime.now(UTC).isoformat(),
    }
    wrong_record = client.post(
        f"/v1/retention/chat-assets/{asset_id}/prepare",
        headers=service_headers,
        json=payload,
    )
    assert wrong_record.status_code == 200
    assert wrong_record.json() == {
        "asset_id": asset_id,
        "disposition": "protected",
        "status": "retained",
    }
    payload["record_id"] = record_id
    prepared = client.post(
        f"/v1/retention/chat-assets/{asset_id}/prepare",
        headers=service_headers,
        json=payload,
    )
    assert prepared.status_code == 200
    assert prepared.json() == {
        "asset_id": asset_id,
        "disposition": "accepted",
        "status": "prepared",
    }
    ops = client.get("/v1/ops/snapshot", headers=service_headers)
    assert ops.json()["retention_prepared_count"] == 1
    assert ops.json()["oldest_retention_prepared_age_seconds"] >= 0
    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None and asset.status == "active"
        assert session.scalar(
            select(func.count(TransferTicket.ticket_id)).where(
                TransferTicket.asset_id == asset_id,
                TransferTicket.revoked_at.is_(None),
            )
        ) == 1
    accepted = client.post(
        f"/v1/retention/chat-assets/{asset_id}/commit",
        headers=service_headers,
        json=payload,
    )
    assert accepted.json() == {
        "asset_id": asset_id,
        "disposition": "accepted",
        "status": "delete_pending",
    }
    committed_ops = client.get("/v1/ops/snapshot", headers=service_headers)
    assert committed_ops.json()["retention_prepared_count"] == 0
    assert committed_ops.json()["oldest_retention_prepared_age_seconds"] is None
    replay = client.post(
        f"/v1/retention/chat-assets/{asset_id}/commit",
        headers=service_headers,
        json=payload,
    )
    assert replay.json() == accepted.json()
    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None and asset.status == "delete_pending"
        assert session.scalar(
            select(func.count(AssetAuditEvent.event_id)).where(
                AssetAuditEvent.asset_id == asset_id,
                AssetAuditEvent.event_type == "retention_delete_requested",
            )
        ) == 1
        assert session.scalar(
            select(func.count(TransferTicket.ticket_id)).where(
                TransferTicket.asset_id == asset_id,
                TransferTicket.revoked_at.is_(None),
            )
        ) == 0


def test_retention_handoff_protects_missing_and_moment_usage(
    client, app, service_headers
) -> None:
    payload = {
        "operation_id": str(uuid.uuid4()),
        "record_id": str(uuid.uuid4()),
        "conversation_id": "conversation-1",
        "requested_at": datetime.now(UTC).isoformat(),
    }
    missing_id = "att_" + "f" * 32
    missing = client.post(
        f"/v1/retention/chat-assets/{missing_id}/prepare",
        headers=service_headers,
        json=payload,
    )
    assert missing.json() == {
        "asset_id": missing_id,
        "disposition": "protected",
        "status": "retained",
    }

    # Even deliberately matching IDs cannot cross the immutable usage domain.
    created = _intent(
        client, service_headers, client_id="usage-protected", kind="image"
    )
    asset_id = created.json()["asset"]["asset_id"]
    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        asset.usage = "moment_image"
        asset.scope_id = "mom_" + "1" * 32
        asset.binding_status = "committed"
        asset.binding_client_id = "moment-client"
        asset.bound_resource_id = asset.scope_id
        asset.committed_at = datetime.now(UTC)
        session.commit()
    payload["record_id"] = "mom_" + "1" * 32
    payload["conversation_id"] = "mom_" + "1" * 32
    protected = client.post(
        f"/v1/retention/chat-assets/{asset_id}/prepare",
        headers=service_headers,
        json=payload,
    )
    assert protected.json()["disposition"] == "protected"
    with app.state.database.session_factory() as session:
        assert session.get(Asset, asset_id).status == "pending_upload"


def test_expired_replay_rechecks_pending_quota_under_dataset_lock(
    api_settings, service_headers
) -> None:
    app, client = _client_for(
        api_settings,
        max_pending_uploads_per_owner=1,
    )
    try:
        first = _intent(client, service_headers, client_id="expired-reopen")
        assert first.status_code == 201
        first_id = first.json()["asset"]["asset_id"]
        with app.state.database.session_factory() as session:
            asset = session.get(Asset, first_id)
            assert asset is not None
            asset.status = "expired"
            session.commit()
        assert _intent(client, service_headers, client_id="pending-slot").status_code == 201
        replay = _intent(client, service_headers, client_id="expired-reopen")
        assert replay.status_code == 429
        with app.state.database.session_factory() as session:
            assert session.get(Asset, first_id).status == "expired"
    finally:
        _close(app)


def test_generated_thumbnail_hard_limit_matches_reserved_budget(tmp_path) -> None:
    from PIL import Image

    source = tmp_path / "source.png"
    thumbnail = tmp_path / "thumbnail.png"
    Image.new("RGB", (32, 32), (10, 20, 30)).save(source, format="PNG")
    with pytest.raises(
        ContentValidationError, match="thumbnail exceeds byte limit"
    ):
        validate_content(
            source,
            kind="image",
            filename="source.png",
            declared_media_type="image/png",
            limits=ValidationLimits(thumbnail_max_bytes=1),
            thumbnail_path=thumbnail,
        )
