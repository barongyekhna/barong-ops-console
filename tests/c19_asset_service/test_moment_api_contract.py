from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from c19_asset_service.models import Asset, TransferTicket

from c19_asset_test_helpers import moment_upload_payload, upload_payload


MOMENT_ID = "mom_" + "a" * 32
OTHER_MOMENT_ID = "mom_" + "b" * 32


def _moment_intent(client, service_headers, body: bytes = b"png declaration"):
    payload = moment_upload_payload(body)
    response = client.post(
        "/v1/moment-assets/upload-intents",
        headers=service_headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json(), payload


def _make_active(app, asset_id: str, *, thumbnail: bool = False) -> None:
    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        asset.status = "active"
        asset.active_object_key = "aa/bb/" + "c" * 28
        asset.actual_size_bytes = asset.declared_size_bytes
        asset.actual_sha256_hex = asset.declared_sha256_hex
        asset.incoming_object_key = None
        asset.activated_at = datetime.now(UTC)
        asset.updated_at = datetime.now(UTC)
        if thumbnail:
            asset.thumbnail_object_key = "dd/ee/" + "f" * 28
            asset.thumbnail_size_bytes = 7
            asset.thumbnail_sha256_hex = hashlib.sha256(b"preview").hexdigest()
            asset.thumbnail_media_type = "image/png"
        session.commit()


def _commit_moment(client, app, service_headers, asset_id: str) -> None:
    _make_active(app, asset_id, thumbnail=True)
    prepare = {
        "owner_user_id": "user-1",
        "scope_id": MOMENT_ID,
        "binding_client_id": "client-moment-001",
    }
    assert client.post(
        f"/v1/moment-assets/{asset_id}/bindings/prepare",
        headers=service_headers,
        json=prepare,
    ).status_code == 200
    assert client.post(
        f"/v1/moment-assets/{asset_id}/bindings/commit",
        headers=service_headers,
        json={**prepare, "bound_resource_id": MOMENT_ID},
    ).status_code == 200


def _download_ticket(client, service_headers, asset_id: str) -> str:
    response = client.post(
        f"/v1/moment-assets/{asset_id}/download-intents",
        headers=service_headers,
        json={
            "owner_user_id": "user-1",
            "reader_user_id": "reader-1",
            "scope_id": MOMENT_ID,
            "bound_resource_id": MOMENT_ID,
            "variant": "original",
            "disposition": "attachment",
            "asset_version": 1,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["download_ticket"]


def test_moment_contract_is_private_image_only_and_sanitized(
    client, service_headers
):
    payload = moment_upload_payload(b"image")
    assert client.post(
        "/v1/moment-assets/upload-intents", json=payload
    ).status_code == 401

    invalid_scope = dict(payload, scope_id="client-controlled-draft")
    response = client.post(
        "/v1/moment-assets/upload-intents",
        headers=service_headers,
        json=invalid_scope,
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid request"}
    assert "client-controlled" not in response.text

    ordinary_file = dict(
        payload,
        kind="file",
        filename="private.pdf",
        media_type="application/pdf",
    )
    response = client.post(
        "/v1/moment-assets/upload-intents",
        headers=service_headers,
        json=ordinary_file,
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "invalid request"}
    assert "private.pdf" not in response.text


def test_moment_upload_is_idempotent_and_never_crosses_usage_or_scope(
    client, app, service_headers
):
    first, payload = _moment_intent(client, service_headers)
    replay = client.post(
        "/v1/moment-assets/upload-intents",
        headers=service_headers,
        json=payload,
    )
    assert replay.status_code == 201
    assert replay.json()["asset"]["asset_id"] == first["asset"]["asset_id"]
    assert replay.json()["upload_ticket"] != first["upload_ticket"]
    assert first["asset"]["usage"] == "moment_image"
    assert first["asset"]["scope_id"] == MOMENT_ID
    assert "conversation_id" not in first["asset"]

    different_scope = dict(payload, scope_id=OTHER_MOMENT_ID)
    assert client.post(
        "/v1/moment-assets/upload-intents",
        headers=service_headers,
        json=different_scope,
    ).status_code == 409

    chat_payload = upload_payload(
        b"png declaration",
        client_asset_id=str(payload["client_asset_id"]),
        filename="moment.png",
        media_type="image/png",
        kind="image",
    )
    assert client.post(
        "/v1/upload-intents", headers=service_headers, json=chat_payload
    ).status_code == 409

    asset_id = first["asset"]["asset_id"]
    visible = client.get(
        f"/v1/moment-assets/{asset_id}",
        headers=service_headers,
        params={"owner_user_id": "user-1", "scope_id": MOMENT_ID},
    )
    assert visible.status_code == 200
    for params in (
        {"owner_user_id": "user-2", "scope_id": MOMENT_ID},
        {"owner_user_id": "user-1", "scope_id": OTHER_MOMENT_ID},
    ):
        hidden = client.get(
            f"/v1/moment-assets/{asset_id}",
            headers=service_headers,
            params=params,
        )
        assert hidden.status_code == 404

    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        assert asset.usage == "moment_image"
        assert asset.scope_id == MOMENT_ID
        assert asset.conversation_id is None


def test_moment_binding_is_single_scope_idempotent_and_downloadable(
    client, app, service_headers, gateway_headers
):
    result, _ = _moment_intent(client, service_headers)
    asset_id = result["asset"]["asset_id"]
    _make_active(app, asset_id, thumbnail=True)
    prepare = {
        "owner_user_id": "user-1",
        "scope_id": MOMENT_ID,
        "binding_client_id": "client-moment-001",
    }
    wrong_scope = {**prepare, "scope_id": OTHER_MOMENT_ID}
    assert client.post(
        f"/v1/moment-assets/{asset_id}/bindings/prepare",
        headers=service_headers,
        json=wrong_scope,
    ).status_code == 404
    prepared = client.post(
        f"/v1/moment-assets/{asset_id}/bindings/prepare",
        headers=service_headers,
        json=prepare,
    )
    assert prepared.status_code == 200
    assert prepared.json()["binding_status"] == "prepared"
    conflict = client.post(
        f"/v1/moment-assets/{asset_id}/bindings/prepare",
        headers=service_headers,
        json={**prepare, "binding_client_id": "different-client-moment"},
    )
    assert conflict.status_code == 409

    mismatched_commit = client.post(
        f"/v1/moment-assets/{asset_id}/bindings/commit",
        headers=service_headers,
        json={**prepare, "bound_resource_id": OTHER_MOMENT_ID},
    )
    assert mismatched_commit.status_code == 422
    committed = client.post(
        f"/v1/moment-assets/{asset_id}/bindings/commit",
        headers=service_headers,
        json={**prepare, "bound_resource_id": MOMENT_ID},
    )
    assert committed.status_code == 200
    assert committed.json()["binding_status"] == "committed"
    assert client.post(
        f"/v1/moment-assets/{asset_id}/bindings/commit",
        headers=service_headers,
        json={**prepare, "bound_resource_id": MOMENT_ID},
    ).status_code == 200

    # A dedicated Moment asset is never addressable through the legacy chat API.
    assert client.get(
        f"/v1/assets/{asset_id}",
        headers=service_headers,
        params={"owner_user_id": "user-1", "conversation_id": MOMENT_ID},
    ).status_code == 404

    for variant, disposition in (("original", "attachment"), ("thumbnail", "inline")):
        response = client.post(
            f"/v1/moment-assets/{asset_id}/download-intents",
            headers=service_headers,
            json={
                "owner_user_id": "user-1",
                "reader_user_id": "reader-1",
                "scope_id": MOMENT_ID,
                "bound_resource_id": MOMENT_ID,
                "variant": variant,
                "disposition": disposition,
                "asset_version": 1,
            },
        )
        assert response.status_code == 201
        ticket = response.json()["download_ticket"]
        old_inspect = client.post(
            "/v1/transfers/inspect",
            headers=service_headers,
            json={"ticket": ticket, "direction": "download", "method": "GET"},
        )
        assert old_inspect.status_code == 404
        scoped = client.post(
            "/v2/transfers/inspect",
            headers=service_headers,
            json={"ticket": ticket, "direction": "download", "method": "GET"},
        )
        assert scoped.status_code == 200
        assert scoped.json() == {
            "asset_id": asset_id,
            "owner_user_id": "user-1",
            "reader_user_id": "reader-1",
            "usage": "moment_image",
            "scope_id": MOMENT_ID,
            "bound_resource_id": MOMENT_ID,
            "variant": variant,
            "version": 1,
            "expires_at": response.json()["expires_at"],
        }
        authorized = client.post(
            "/internal/downloads/authorize",
            headers=gateway_headers,
            json={"ticket": ticket, "method": "GET"},
        )
        assert authorized.status_code == 200


def test_v2_inspect_preserves_chat_and_exposes_generic_scope(
    client, service_headers
):
    payload = upload_payload()
    result = client.post(
        "/v1/upload-intents", headers=service_headers, json=payload
    ).json()
    ticket = result["upload_ticket"]
    legacy = client.post(
        "/v1/transfers/inspect",
        headers=service_headers,
        json={"ticket": ticket, "direction": "upload", "method": "PUT"},
    )
    assert legacy.status_code == 200
    assert set(legacy.json()) == {
        "asset_id",
        "owner_user_id",
        "reader_user_id",
        "conversation_id",
        "record_id",
        "variant",
        "version",
        "expires_at",
    }
    scoped = client.post(
        "/v2/transfers/inspect",
        headers=service_headers,
        json={"ticket": ticket, "direction": "upload", "method": "PUT"},
    )
    assert scoped.status_code == 200
    assert scoped.json()["usage"] == "chat_message"
    assert scoped.json()["scope_id"] == "conversation-1"
    assert scoped.json()["bound_resource_id"] is None
    assert "conversation_id" not in scoped.json()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("owner_user_id", "another-owner"),
        ("usage", "chat_message"),
    ),
)
def test_ticket_asset_scope_tampering_is_indistinguishable(
    client, app, service_headers, field, value
):
    result, _ = _moment_intent(
        client,
        service_headers,
        body=f"tamper-{field}".encode(),
    )
    asset_id = result["asset"]["asset_id"]
    _commit_moment(client, app, service_headers, asset_id)
    ticket = _download_ticket(client, service_headers, asset_id)
    with app.state.database.session_factory() as session:
        row = session.scalar(
            select(TransferTicket).where(
                TransferTicket.ticket_sha256
                == hashlib.sha256(ticket.encode("ascii")).hexdigest()
            )
        )
        assert row is not None
        setattr(row, field, value)
        session.commit()
    response = client.post(
        "/v2/transfers/inspect",
        headers=service_headers,
        json={"ticket": ticket, "direction": "download", "method": "GET"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "transfer not found"}


@pytest.mark.parametrize("field", ("scope_id", "bound_resource_id"))
def test_moment_ticket_database_rejects_cross_scope_tampering(
    client, app, service_headers, field
):
    result, _ = _moment_intent(client, service_headers)
    asset_id = result["asset"]["asset_id"]
    _commit_moment(client, app, service_headers, asset_id)
    ticket = _download_ticket(client, service_headers, asset_id)
    with app.state.database.session_factory() as session:
        row = session.scalar(
            select(TransferTicket).where(
                TransferTicket.ticket_sha256
                == hashlib.sha256(ticket.encode("ascii")).hexdigest()
            )
        )
        assert row is not None
        setattr(row, field, OTHER_MOMENT_ID)
        with pytest.raises(IntegrityError):
            session.commit()


def test_gateway_completion_returns_moment_scope(
    client, service_headers, gateway_headers
):
    body = b"moment gateway bytes"
    result, _ = _moment_intent(client, service_headers, body)
    ticket = result["upload_ticket"]
    assert client.post(
        "/v2/transfers/inspect",
        json={"ticket": ticket, "direction": "upload", "method": "PUT"},
    ).status_code == 401
    assert client.post(
        "/v1/transfers/inspect",
        headers=service_headers,
        json={"ticket": ticket, "direction": "upload", "method": "PUT"},
    ).status_code == 404
    scoped = client.post(
        "/v2/transfers/inspect",
        headers=service_headers,
        json={"ticket": ticket, "direction": "upload", "method": "PUT"},
    )
    assert scoped.status_code == 200
    assert scoped.json()["usage"] == "moment_image"
    assert scoped.json()["scope_id"] == MOMENT_ID
    assert scoped.json()["bound_resource_id"] is None
    authorized = client.post(
        "/internal/uploads/authorize",
        headers=gateway_headers,
        json={"ticket": ticket, "method": "PUT", "content_length": len(body)},
    )
    assert authorized.status_code == 200
    completed = client.post(
        "/internal/uploads/complete",
        headers=gateway_headers,
        json={
            "ticket": ticket,
            "size_bytes": len(body),
            "sha256_hex": hashlib.sha256(body).hexdigest(),
        },
    )
    assert completed.status_code == 200
    assert completed.json()["usage"] == "moment_image"
    assert completed.json()["scope_id"] == MOMENT_ID
    assert "conversation_id" not in completed.json()
