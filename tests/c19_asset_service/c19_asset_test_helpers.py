from __future__ import annotations

import hashlib
from datetime import UTC, datetime


SERVICE_TOKEN = "service-token-" + "s" * 32
GATEWAY_TOKEN = "gateway-token-" + "g" * 32


def upload_payload(
    body: bytes = b"hello asset\n",
    *,
    client_asset_id: str = "client-asset-001",
    filename: str = "notes.txt",
    media_type: str = "text/plain",
    kind: str = "file",
) -> dict[str, object]:
    return {
        "client_asset_id": client_asset_id,
        "owner_user_id": "user-1",
        "conversation_id": "conversation-1",
        "kind": kind,
        "filename": filename,
        "media_type": media_type,
        "size_bytes": len(body),
        "sha256_hex": hashlib.sha256(body).hexdigest(),
        "requested_at": datetime.now(UTC).isoformat(),
    }


def moment_upload_payload(
    body: bytes,
    *,
    client_asset_id: str = "moment-client-asset-001",
    scope_id: str = "mom_" + "a" * 32,
    filename: str = "moment.png",
    media_type: str = "image/png",
) -> dict[str, object]:
    return {
        "client_asset_id": client_asset_id,
        "owner_user_id": "user-1",
        "scope_id": scope_id,
        "kind": "image",
        "filename": filename,
        "media_type": media_type,
        "size_bytes": len(body),
        "sha256_hex": hashlib.sha256(body).hexdigest(),
        "requested_at": datetime.now(UTC).isoformat(),
    }
