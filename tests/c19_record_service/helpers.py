from __future__ import annotations

from datetime import UTC, datetime, timedelta

from c19_record_service.schemas import RecordAppendRequest


SERVICE_TOKEN = "service-token-" + "x" * 32
CURSOR_SECRET = "cursor-secret-" + "y" * 32


def make_record(
    number: int,
    *,
    conversation_id: str = "conversation-1",
    sender_user_id: str = "user-1",
    recipient_user_ids: list[str] | None = None,
    content: str | None = None,
    content_type: str = "text",
    created_at: datetime | None = None,
) -> RecordAppendRequest:
    return RecordAppendRequest(
        client_message_id=f"client-{number}",
        conversation_id=conversation_id,
        sender_user_id=sender_user_id,
        recipient_user_ids=recipient_user_ids or ["user-2"],
        content_type=content_type,
        content=content or f"message {number}",
        created_at=created_at or datetime.now(UTC) + timedelta(microseconds=number),
        sender_org_id="org-1",
        recipient_org_ids=["org-2"],
        metadata={"source": "test"},
    )
