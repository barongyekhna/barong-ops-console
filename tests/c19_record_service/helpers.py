from __future__ import annotations

from datetime import UTC, datetime, timedelta

from c19_record_service.schemas import RecordAppendRequest, RecordAssetReference


SERVICE_TOKEN = "service-token-" + "x" * 32
CURSOR_SECRET = "cursor-secret-" + "y" * 32


def make_asset(
    number: int,
    *,
    kind: str = "image",
    ordinal: int = 0,
    filename: str | None = None,
) -> RecordAssetReference:
    return RecordAssetReference(
        asset_id=f"att_{number:032x}",
        client_asset_id=f"client-asset-{number}",
        kind=kind,
        filename=filename
        or (
            f"image-{number}.jpg"
            if kind == "image"
            else f"file-{number}.pdf"
        ),
        media_type="image/jpeg" if kind == "image" else "application/pdf",
        size_bytes=1000 + number,
        sha256_hex=f"{number:064x}",
        version=1,
        ordinal=ordinal,
    )


def make_record(
    number: int,
    *,
    conversation_id: str = "conversation-1",
    sender_user_id: str = "user-1",
    recipient_user_ids: list[str] | None = None,
    content: str | None = None,
    content_type: str = "text",
    created_at: datetime | None = None,
    assets: list[RecordAssetReference] | None = None,
) -> RecordAppendRequest:
    return RecordAppendRequest(
        client_message_id=f"client-{number}",
        conversation_id=conversation_id,
        sender_user_id=sender_user_id,
        recipient_user_ids=recipient_user_ids or ["user-2"],
        content_type=content_type,
        content=content if content is not None else f"message {number}",
        created_at=created_at or datetime.now(UTC) + timedelta(microseconds=number),
        sender_org_id="org-1",
        recipient_org_ids=["org-2"],
        metadata={"source": "test"},
        assets=assets or [],
    )
