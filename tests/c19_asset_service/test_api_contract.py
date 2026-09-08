from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from c19_asset_service.models import Asset, TransferTicket
from c19_asset_service.repository import (
    authorize_gateway_upload,
    create_upload_intent,
    inspect_transfer,
)
from c19_asset_service.schemas import (
    GatewayUploadAuthorizeRequest,
    TransferInspectRequest,
    UploadIntentRequest,
)

from c19_asset_test_helpers import upload_payload


def _intent(client, service_headers, body=b"hello asset\n", **overrides):
    payload = upload_payload(body, **overrides)
    response = client.post("/v1/upload-intents", headers=service_headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json(), payload


def _make_active(app, asset_id: str, *, object_key: str = "aa/bb/cc") -> None:
    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        asset.status = "active"
        asset.active_object_key = object_key
        asset.actual_size_bytes = asset.declared_size_bytes
        asset.actual_sha256_hex = asset.declared_sha256_hex
        asset.incoming_object_key = None
        asset.activated_at = datetime.now(UTC)
        asset.updated_at = datetime.now(UTC)
        session.commit()


def test_every_http_method_and_path_is_registered_once(app):
    registrations = [
        (method, route.path)
        for route in app.routes
        for method in (route.methods or set())
    ]
    assert len(registrations) == len(set(registrations))


def test_private_ops_snapshot_is_aggregate_only(
    client, service_headers
) -> None:
    secret_filename = "private-ops-name.txt"
    created, _ = _intent(
        client,
        service_headers,
        filename=secret_filename,
        client_asset_id="private-ops-client-id",
    )
    response = client.get("/v1/ops/snapshot", headers=service_headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["asset_states"]["pending_upload"] == 1
    assert body["asset_usages"] == {"chat_message": 1, "moment_image": 0}
    assert body["reserved_asset_files"] == 1
    assert body["reserved_asset_bytes"] == created["asset"]["size_bytes"]
    assert body["active_transfer_tickets"] == 1
    assert body["audit_events"] >= 1
    for forbidden in (
        secret_filename,
        "private-ops-client-id",
        created["asset"]["asset_id"],
        created["upload_ticket"],
    ):
        assert forbidden not in response.text
    assert client.get("/v1/ops/snapshot").status_code == 401


def test_private_auth_and_sanitized_validation(client, service_headers):
    assert client.post("/v1/upload-intents", json={}).status_code == 401
    wrong = client.post(
        "/v1/upload-intents",
        headers={"Authorization": "Bearer " + "x" * 64},
        json={},
    )
    assert wrong.status_code == 401
    payload = upload_payload(filename="private-name.txt")
    payload["unexpected"] = "secret-extra"
    invalid = client.post(
        "/v1/upload-intents", headers=service_headers, json=payload
    )
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "invalid request"}
    assert "private-name" not in invalid.text
    assert "secret-extra" not in invalid.text


def test_upload_contract_ticket_hash_and_scope(client, app, service_headers):
    result, _ = _intent(client, service_headers)
    asset = result["asset"]
    ticket = result["upload_ticket"]
    assert asset["asset_id"].startswith("att_")
    assert len(asset["asset_id"]) == 36
    assert asset["status"] == "pending_upload"
    assert ticket and len(ticket) == 43
    assert "object_key" not in result
    assert ticket not in result["asset"].values()
    with app.state.database.session_factory() as session:
        row = session.scalar(select(TransferTicket))
        assert row is not None
        assert row.ticket_sha256 == hashlib.sha256(ticket.encode("ascii")).hexdigest()
        assert ticket != row.ticket_sha256
    visible = client.get(
        f"/v1/assets/{asset['asset_id']}",
        headers=service_headers,
        params={"owner_user_id": "user-1", "conversation_id": "conversation-1"},
    )
    assert visible.status_code == 200
    hidden = client.get(
        f"/v1/assets/{asset['asset_id']}",
        headers=service_headers,
        params={"owner_user_id": "user-2", "conversation_id": "conversation-1"},
    )
    assert hidden.status_code == 404
    assert "object" not in hidden.text.lower()


def test_upload_idempotency_conflict_and_pending_quota(
    client, app, service_headers
):
    first, payload = _intent(client, service_headers)
    replay_payload = dict(payload)
    replay_payload["requested_at"] = (
        datetime.now(UTC) + timedelta(seconds=1)
    ).isoformat()
    replay = client.post(
        "/v1/upload-intents", headers=service_headers, json=replay_payload
    )
    assert replay.status_code == 201
    assert replay.json()["asset"]["asset_id"] == first["asset"]["asset_id"]
    assert replay.json()["upload_ticket"] != first["upload_ticket"]
    first_still_valid = client.post(
        "/v1/transfers/inspect",
        headers=service_headers,
        json={
            "ticket": first["upload_ticket"],
            "direction": "upload",
            "method": "PUT",
        },
    )
    assert first_still_valid.status_code == 200
    conflict_payload = dict(payload)
    conflict_payload["sha256_hex"] = "f" * 64
    conflict = client.post(
        "/v1/upload-intents", headers=service_headers, json=conflict_payload
    )
    assert conflict.status_code == 409
    _intent(client, service_headers, client_asset_id="client-asset-002")
    _intent(client, service_headers, client_asset_id="client-asset-003")
    quota_payload = upload_payload(client_asset_id="client-asset-004")
    quota = client.post(
        "/v1/upload-intents", headers=service_headers, json=quota_payload
    )
    assert quota.status_code == 429
    # No raw ticket or physical locator is retained on an asset row.
    with app.state.database.session_factory() as session:
        db_asset = session.get(Asset, first["asset"]["asset_id"])
        assert db_asset is not None
        assert not hasattr(db_asset, "upload_ticket")


def test_two_concurrent_first_intents_resolve_to_one_asset(
    app, api_settings
):
    payload = upload_payload(client_asset_id="concurrent-first-intent")
    request = UploadIntentRequest.model_validate(payload)
    barrier = threading.Barrier(2)

    def synchronize_first_asset_flush(session, flush_context, instances):
        del flush_context, instances
        if any(
            isinstance(value, Asset)
            and value.client_asset_id == "concurrent-first-intent"
            for value in session.new
        ):
            barrier.wait(timeout=5)

    def create():
        with app.state.database.session_factory() as session:
            return create_upload_intent(session, request, api_settings)

    event.listen(Session, "before_flush", synchronize_first_asset_flush)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [future.result(timeout=10) for future in (executor.submit(create), executor.submit(create))]
    finally:
        event.remove(Session, "before_flush", synchronize_first_asset_flush)
    assert results[0].asset.asset_id == results[1].asset.asset_id
    assert results[0].upload_ticket != results[1].upload_ticket
    for result in results:
        assert result.upload_ticket is not None
        with app.state.database.session_factory() as session:
            inspected = inspect_transfer(
                session,
                TransferInspectRequest(
                    ticket=result.upload_ticket,
                    direction="upload",
                    method="PUT",
                ),
            )
            assert inspected.asset_id == result.asset.asset_id
        with app.state.database.session_factory() as session:
            authorized = authorize_gateway_upload(
                session,
                GatewayUploadAuthorizeRequest(
                    ticket=result.upload_ticket,
                    method="PUT",
                    content_length=int(payload["size_bytes"]),
                ),
                api_settings,
            )
            assert authorized.asset_id == result.asset.asset_id
            assert authorized.upload_state == "ready"
    with app.state.database.session_factory() as session:
        assets = list(
            session.scalars(
                select(Asset).where(
                    Asset.client_asset_id == "concurrent-first-intent"
                )
            )
        )
    assert len(assets) == 1


def test_extension_media_kind_and_compiled_size_validation(client, service_headers):
    mismatch = upload_payload(filename="photo.jpg", media_type="image/png", kind="image")
    response = client.post(
        "/v1/upload-intents", headers=service_headers, json=mismatch
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid request"}
    oversized = upload_payload()
    oversized["size_bytes"] = 257 * 1024 * 1024
    response = client.post(
        "/v1/upload-intents", headers=service_headers, json=oversized
    )
    assert response.status_code == 422
    # Programs are refused; every other file is admitted, unknown containers
    # as an opaque octet stream.
    executable = upload_payload(
        filename="setup.exe", media_type="application/octet-stream", kind="file"
    )
    response = client.post(
        "/v1/upload-intents", headers=service_headers, json=executable
    )
    assert response.status_code == 422
    for index, (filename, media_type) in enumerate(
        (
            ("演示.mp4", "video/mp4"),
            ("模具.skp", "application/octet-stream"),
            ("无扩展名", "application/octet-stream"),
        )
    ):
        admitted = upload_payload(filename=filename, media_type=media_type, kind="file")
        admitted["client_asset_id"] = f"admitted-any-file-{index}"
        response = client.post(
            "/v1/upload-intents", headers=service_headers, json=admitted
        )
        assert response.status_code == 201, response.text
    bidi = upload_payload(filename="report\u202epdf.txt")
    response = client.post(
        "/v1/upload-intents", headers=service_headers, json=bidi
    )
    assert response.status_code == 422


def test_pending_upload_ticket_cap_rejects_without_revoking_successes(
    client, service_headers, api_settings
):
    first, payload = _intent(
        client, service_headers, client_asset_id="ticket-cap-asset"
    )
    tickets = [first["upload_ticket"]]
    for _ in range(api_settings.max_upload_tickets_per_asset - 1):
        replay = client.post(
            "/v1/upload-intents", headers=service_headers, json=payload
        )
        assert replay.status_code == 201
        tickets.append(replay.json()["upload_ticket"])
    capped = client.post(
        "/v1/upload-intents", headers=service_headers, json=payload
    )
    assert capped.status_code == 429
    for ticket in tickets:
        inspection = client.post(
            "/v1/transfers/inspect",
            headers=service_headers,
            json={"ticket": ticket, "direction": "upload", "method": "PUT"},
        )
        assert inspection.status_code == 200


def test_upload_inspect_authorize_complete_and_lost_response_retry(
    client, service_headers, gateway_headers
):
    body = b"gateway recovery\n"
    result, _ = _intent(client, service_headers, body)
    ticket = result["upload_ticket"]
    asset_id = result["asset"]["asset_id"]
    inspection = client.post(
        "/v1/transfers/inspect",
        headers=service_headers,
        json={"ticket": ticket, "direction": "upload", "method": "PUT"},
    )
    assert inspection.status_code == 200
    assert inspection.json()["asset_id"] == asset_id
    assert inspection.json()["reader_user_id"] is None
    first = client.post(
        "/internal/uploads/authorize",
        headers=gateway_headers,
        json={"ticket": ticket, "method": "PUT", "content_length": len(body)},
    )
    assert first.status_code == 200
    assert first.json()["upload_state"] == "ready"
    assert first.json()["object_key"]
    # Retrying authorization after bytes landed but before the completion response
    # is intentionally safe and returns the same physical reservation.
    retry = client.post(
        "/internal/uploads/authorize",
        headers=gateway_headers,
        json={"ticket": ticket, "method": "PUT", "content_length": len(body)},
    )
    assert retry.status_code == 200
    assert retry.json()["object_key"] == first.json()["object_key"]
    # Nginx/Barong performs inspection again on every PUT retry, so consumed
    # upload tickets must remain inspectable for recovery until their TTL.
    retry_inspection = client.post(
        "/v1/transfers/inspect",
        headers=service_headers,
        json={"ticket": ticket, "direction": "upload", "method": "PUT"},
    )
    assert retry_inspection.status_code == 200
    completion = {
        "ticket": ticket,
        "size_bytes": len(body),
        "sha256_hex": hashlib.sha256(body).hexdigest(),
    }
    assert client.post(
        "/internal/uploads/complete", headers=gateway_headers, json=completion
    ).status_code == 200
    # A lost 200 response can be replayed without duplicating or changing state.
    assert client.post(
        "/internal/uploads/complete", headers=gateway_headers, json=completion
    ).status_code == 200
    after = client.post(
        "/internal/uploads/authorize",
        headers=gateway_headers,
        json={"ticket": ticket, "method": "PUT", "content_length": len(body)},
    )
    assert after.status_code == 200
    assert after.json()["upload_state"] == "completed"
    assert after.json()["object_key"] is None
    completed_inspection = client.post(
        "/v1/transfers/inspect",
        headers=service_headers,
        json={"ticket": ticket, "direction": "upload", "method": "PUT"},
    )
    assert completed_inspection.status_code == 200


def test_digest_mismatch_is_rejected_and_ticket_invalidated(
    client, service_headers, gateway_headers
):
    body = b"expected"
    result, _ = _intent(client, service_headers, body)
    ticket = result["upload_ticket"]
    authorization = client.post(
        "/internal/uploads/authorize",
        headers=gateway_headers,
        json={"ticket": ticket, "method": "PUT", "content_length": len(body)},
    )
    assert authorization.status_code == 200
    rejected = client.post(
        "/internal/uploads/complete",
        headers=gateway_headers,
        json={
            "ticket": ticket,
            "size_bytes": len(body),
            "sha256_hex": hashlib.sha256(b"tampered").hexdigest(),
        },
    )
    assert rejected.status_code == 422
    inspection = client.post(
        "/v1/transfers/inspect",
        headers=service_headers,
        json={"ticket": ticket, "direction": "upload", "method": "PUT"},
    )
    assert inspection.status_code == 404


def test_binding_download_ticket_use_limit_and_invalidation(
    client, app, service_headers, gateway_headers
):
    result, _ = _intent(client, service_headers)
    asset_id = result["asset"]["asset_id"]
    _make_active(app, asset_id)
    prepare_body = {
        "owner_user_id": "user-1",
        "conversation_id": "conversation-1",
        "client_message_id": "message-1",
    }
    prepared = client.post(
        f"/v1/assets/{asset_id}/bindings/prepare",
        headers=service_headers,
        json=prepare_body,
    )
    assert prepared.status_code == 200
    assert prepared.json()["binding_status"] == "prepared"
    assert client.post(
        f"/v1/assets/{asset_id}/bindings/prepare",
        headers=service_headers,
        json=prepare_body,
    ).status_code == 200
    conflict = dict(prepare_body, client_message_id="message-2")
    assert client.post(
        f"/v1/assets/{asset_id}/bindings/prepare",
        headers=service_headers,
        json=conflict,
    ).status_code == 409
    commit_body = dict(prepare_body, record_id="record-1")
    committed = client.post(
        f"/v1/assets/{asset_id}/bindings/commit",
        headers=service_headers,
        json=commit_body,
    )
    assert committed.status_code == 200
    assert committed.json()["binding_status"] == "committed"
    download = client.post(
        f"/v1/assets/{asset_id}/download-intents",
        headers=service_headers,
        json={
            "owner_user_id": "user-1",
            "reader_user_id": "user-2",
            "conversation_id": "conversation-1",
            "record_id": "record-1",
            "variant": "original",
            "disposition": "attachment",
            "asset_version": 1,
        },
    )
    assert download.status_code == 201
    ticket = download.json()["download_ticket"]
    inspection = client.post(
        "/v1/transfers/inspect",
        headers=service_headers,
        json={"ticket": ticket, "direction": "download", "method": "GET"},
    )
    assert inspection.status_code == 200
    assert inspection.json()["reader_user_id"] == "user-2"
    for _ in range(3):
        authorized = client.post(
            "/internal/downloads/authorize",
            headers=gateway_headers,
            json={"ticket": ticket, "method": "GET"},
        )
        assert authorized.status_code == 200
        assert authorized.json()["object_key"] == "aa/bb/cc"
        assert "ticket" not in authorized.text
    exhausted = client.post(
        "/internal/downloads/authorize",
        headers=gateway_headers,
        json={"ticket": ticket, "method": "GET"},
    )
    assert exhausted.status_code == 404


def test_binding_commit_rechecks_active_state_after_prepare(
    client, app, service_headers
):
    result, payload = _intent(client, service_headers)
    asset_id = result["asset"]["asset_id"]
    _make_active(app, asset_id)
    prepare_body = {
        "owner_user_id": "user-1",
        "conversation_id": "conversation-1",
        "client_message_id": "message-race",
    }
    assert client.post(
        f"/v1/assets/{asset_id}/bindings/prepare",
        headers=service_headers,
        json=prepare_body,
    ).status_code == 200
    assert client.post(
        f"/v1/assets/{asset_id}/quarantine",
        headers=service_headers,
        json={
            "requested_by_user_id": "user-1",
            "reason": "test state transition",
            "requested_at": payload["requested_at"],
        },
    ).status_code == 200
    commit = client.post(
        f"/v1/assets/{asset_id}/bindings/commit",
        headers=service_headers,
        json={**prepare_body, "record_id": "record-race"},
    )
    assert commit.status_code == 409
    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        assert asset.status == "quarantined"
        assert asset.binding_status == "prepared"
        assert asset.record_id is None


def test_original_inline_and_uncommitted_download_are_rejected(
    client, app, service_headers
):
    result, _ = _intent(client, service_headers)
    asset_id = result["asset"]["asset_id"]
    _make_active(app, asset_id)
    invalid = client.post(
        f"/v1/assets/{asset_id}/download-intents",
        headers=service_headers,
        json={
            "owner_user_id": "user-1",
            "reader_user_id": "user-1",
            "conversation_id": "conversation-1",
            "record_id": "record-1",
            "variant": "original",
            "disposition": "inline",
            "asset_version": 1,
        },
    )
    assert invalid.status_code == 422
    unavailable = client.post(
        f"/v1/assets/{asset_id}/download-intents",
        headers=service_headers,
        json={
            "owner_user_id": "user-1",
            "reader_user_id": "user-1",
            "conversation_id": "conversation-1",
            "record_id": "record-1",
            "variant": "original",
            "disposition": "attachment",
            "asset_version": 1,
        },
    )
    assert unavailable.status_code == 409
