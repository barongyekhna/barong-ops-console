"""Provider-neutral storage contracts for the C19 communication module.

This module performs no HTTP, filesystem, or database I/O.  A separately
configured HTTP adapter can implement the record boundary; default stores
reject every content operation when that configuration is absent or invalid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, NoReturn, Protocol, final, runtime_checkable


StorageCapabilityStatus = Literal["configured", "unconfigured"]
StorageName = Literal["chat_record_store", "chat_asset_store"]
ChatRecordStatus = Literal["sent", "delivered", "read"]
ChatAssetStatus = Literal["active", "quarantined", "deleted"]

CHAT_RECORD_STORE_OPERATIONS = (
    "append_record",
    "list_records",
    "list_user_events",
    "get_user_event_tail",
    "advance_delivery",
    "advance_read",
    "get_unread_position",
    "get_resume_position",
    "delete_records",
    "apply_retention",
)
CHAT_ASSET_STORE_OPERATIONS = (
    "create_upload_intent",
    "finalize_upload",
    "create_download_intent",
    "quarantine_asset",
    "delete_asset",
)


@dataclass(frozen=True, slots=True)
class StorageCapabilityDescription:
    """Observable, non-secret capability state for a C19 storage adapter."""

    store_name: StorageName
    status: StorageCapabilityStatus
    configured: bool
    readable: bool
    writable: bool
    durable: bool
    external_io_enabled: bool
    operations: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class C19StorageCapabilities:
    """Combined capability description exposed to control-plane callers."""

    record_store: StorageCapabilityDescription
    asset_store: StorageCapabilityDescription


@dataclass(frozen=True, slots=True)
class ChatRecordAppendDTO:
    """Idempotent append request for one external chat record.

    A configured provider must treat ``(sender_user_id, client_message_id)`` as
    an idempotency key and return the existing record for a safe retry.
    """

    client_message_id: str
    conversation_id: str
    sender_user_id: str
    recipient_user_ids: tuple[str, ...]
    content_type: str
    content: str
    created_at: datetime
    sender_org_id: str | None = None
    recipient_org_ids: tuple[str, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ChatRecordDTO:
    """Durable provider reference returned after an idempotent append."""

    record_id: str
    client_message_id: str
    conversation_id: str
    sequence: int
    sender_user_id: str
    recipient_user_ids: tuple[str, ...]
    content_type: str
    content: str
    status: ChatRecordStatus
    created_at: datetime
    persisted_at: datetime
    sender_org_id: str | None = None
    recipient_org_ids: tuple[str, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ChatRecordQueryDTO:
    """Opaque-cursor query for an authorized conversation history read."""

    conversation_id: str
    user_id: str
    limit: int = 50
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class ChatRecordPageDTO:
    """One ordered provider-neutral page of chat records."""

    records: tuple[ChatRecordDTO, ...]
    next_cursor: str | None
    latest_sequence: int


@dataclass(frozen=True, slots=True)
class ChatUserEventQueryDTO:
    """Opaque-cursor query for the authenticated user's reconnect feed."""

    user_id: str
    limit: int = 100
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class ChatUserEventDTO:
    """Content-free notification that one durable record is available."""

    event_id: str
    user_id: str
    conversation_id: str
    record_id: str
    record_sequence: int
    event_sequence: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChatUserEventPageDTO:
    """One ordered user-event page used for polling and reconnect."""

    events: tuple[ChatUserEventDTO, ...]
    next_cursor: str | None
    latest_event_sequence: int


@dataclass(frozen=True, slots=True)
class ChatUserEventTailDTO:
    """Content-free cursor at the authenticated user's current event tail."""

    user_id: str
    cursor: str
    latest_event_sequence: int


@dataclass(frozen=True, slots=True)
class ChatPositionAdvanceDTO:
    """Request to advance a delivery or read cursor monotonically."""

    conversation_id: str
    user_id: str
    through_sequence: int
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ChatReceiptPositionDTO:
    """Current monotonic delivery/read position for one participant."""

    conversation_id: str
    user_id: str
    delivered_through_sequence: int
    read_through_sequence: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ChatPositionQueryDTO:
    """Authorized participant query for unread and reconnect state."""

    conversation_id: str
    user_id: str


@dataclass(frozen=True, slots=True)
class ChatUnreadPositionDTO:
    """Unread summary without exposing records outside the cursor read."""

    conversation_id: str
    user_id: str
    unread_count: int
    first_unread_sequence: int | None
    latest_sequence: int


@dataclass(frozen=True, slots=True)
class ChatResumePositionDTO:
    """Opaque reconnect cursor plus monotonic participant positions."""

    conversation_id: str
    user_id: str
    resume_cursor: str | None
    delivered_through_sequence: int
    read_through_sequence: int
    latest_sequence: int


@dataclass(frozen=True, slots=True)
class ChatRecordDeleteCommandDTO:
    """Auditable explicit deletion command for selected records."""

    conversation_id: str
    record_ids: tuple[str, ...]
    requested_by_user_id: str
    reason: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ChatRetentionCommandDTO:
    """Auditable retention command; never an implicit local cleanup."""

    requested_by_user_id: str
    reason: str
    requested_at: datetime
    delete_before: datetime
    conversation_id: str | None = None
    maximum_records: int | None = None


@dataclass(frozen=True, slots=True)
class ChatRecordMutationResultDTO:
    """Provider-neutral acknowledgement for delete/retention commands."""

    affected_count: int
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class ChatAssetUploadMetadataDTO:
    """Metadata used to request an upload; never contains asset bytes."""

    client_asset_id: str
    owner_user_id: str
    filename: str
    media_type: str
    size_bytes: int
    sha256_hex: str
    requested_at: datetime
    conversation_id: str | None = None
    message_id: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ChatAssetUploadHandleDTO:
    """Short-lived opaque handle; it is not an HTTP or provider contract."""

    opaque_handle: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ChatAssetDTO:
    """Metadata-only durable asset reference returned after finalization."""

    asset_id: str
    client_asset_id: str
    owner_user_id: str
    filename: str
    media_type: str
    size_bytes: int
    sha256_hex: str
    status: ChatAssetStatus
    created_at: datetime
    conversation_id: str | None = None
    message_id: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()


ChatAssetReferenceDTO = ChatAssetDTO


@dataclass(frozen=True, slots=True)
class ChatAssetDownloadIntentDTO:
    """Short-lived opaque locator returned after an authorized read check."""

    asset_id: str
    opaque_locator: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ChatAssetQuarantineCommandDTO:
    """Auditable command that makes an asset unavailable for download."""

    asset_id: str
    requested_by_user_id: str
    reason: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ChatAssetDeleteCommandDTO:
    """Auditable hard-delete request for an already authorized asset."""

    asset_id: str
    requested_by_user_id: str
    reason: str
    requested_at: datetime


class C19StorageUnconfiguredError(RuntimeError):
    """Raised when content storage is accessed before provider configuration."""

    def __init__(self, *, store_name: StorageName, operation: str) -> None:
        self.store_name = store_name
        self.operation = operation
        super().__init__(
            f"C19 {store_name} is unconfigured; {operation} is blocked "
            "(fail-closed)."
        )


@runtime_checkable
class ChatRecordStore(Protocol):
    """Async contract for durable, ordered external chat record storage."""

    @property
    def capability(self) -> StorageCapabilityDescription:
        ...

    async def append_record(self, record: ChatRecordAppendDTO) -> ChatRecordDTO:
        ...

    async def list_records(self, query: ChatRecordQueryDTO) -> ChatRecordPageDTO:
        ...

    async def list_user_events(
        self,
        query: ChatUserEventQueryDTO,
    ) -> ChatUserEventPageDTO:
        ...

    async def get_user_event_tail(self, user_id: str) -> ChatUserEventTailDTO:
        ...

    async def advance_delivery(
        self,
        command: ChatPositionAdvanceDTO,
    ) -> ChatReceiptPositionDTO:
        """Advance only; a provider must never move this position backwards."""

        ...

    async def advance_read(
        self,
        command: ChatPositionAdvanceDTO,
    ) -> ChatReceiptPositionDTO:
        """Advance only; a provider must never move this position backwards."""

        ...

    async def get_unread_position(
        self,
        query: ChatPositionQueryDTO,
    ) -> ChatUnreadPositionDTO:
        ...

    async def get_resume_position(
        self,
        query: ChatPositionQueryDTO,
    ) -> ChatResumePositionDTO:
        ...

    async def delete_records(
        self,
        command: ChatRecordDeleteCommandDTO,
    ) -> ChatRecordMutationResultDTO:
        ...

    async def apply_retention(
        self,
        command: ChatRetentionCommandDTO,
    ) -> ChatRecordMutationResultDTO:
        ...


@runtime_checkable
class ChatAssetStore(Protocol):
    """Intent-based async contract that never proxies large asset bodies."""

    @property
    def capability(self) -> StorageCapabilityDescription:
        ...

    async def create_upload_intent(
        self,
        metadata: ChatAssetUploadMetadataDTO,
    ) -> ChatAssetUploadHandleDTO:
        ...

    async def finalize_upload(
        self,
        handle: ChatAssetUploadHandleDTO,
    ) -> ChatAssetDTO:
        ...

    async def create_download_intent(
        self,
        asset_id: str,
    ) -> ChatAssetDownloadIntentDTO:
        ...

    async def quarantine_asset(
        self,
        command: ChatAssetQuarantineCommandDTO,
    ) -> ChatAssetDTO:
        ...

    async def delete_asset(self, command: ChatAssetDeleteCommandDTO) -> None:
        ...


CHAT_RECORD_STORAGE_UNCONFIGURED = StorageCapabilityDescription(
    store_name="chat_record_store",
    status="unconfigured",
    configured=False,
    readable=False,
    writable=False,
    durable=False,
    external_io_enabled=False,
    operations=CHAT_RECORD_STORE_OPERATIONS,
    reason="No vetted C19 chat record provider is configured.",
)

CHAT_ASSET_STORAGE_UNCONFIGURED = StorageCapabilityDescription(
    store_name="chat_asset_store",
    status="unconfigured",
    configured=False,
    readable=False,
    writable=False,
    durable=False,
    external_io_enabled=False,
    operations=CHAT_ASSET_STORE_OPERATIONS,
    reason="No vetted C19 chat asset provider is configured.",
)

C19_STORAGE_CAPABILITIES = C19StorageCapabilities(
    record_store=CHAT_RECORD_STORAGE_UNCONFIGURED,
    asset_store=CHAT_ASSET_STORAGE_UNCONFIGURED,
)


class _UnconfiguredStore:
    __slots__ = ()

    store_name: StorageName

    def _fail(self, operation: str) -> NoReturn:
        raise C19StorageUnconfiguredError(
            store_name=self.store_name,
            operation=operation,
        )


@final
class UnconfiguredChatRecordStore(_UnconfiguredStore):
    """Default record store; rejects every record operation."""

    __slots__ = ()

    store_name: Literal["chat_record_store"] = "chat_record_store"

    @property
    def capability(self) -> StorageCapabilityDescription:
        return CHAT_RECORD_STORAGE_UNCONFIGURED

    async def append_record(self, record: ChatRecordAppendDTO) -> ChatRecordDTO:
        del record
        self._fail("append_record")

    async def list_records(self, query: ChatRecordQueryDTO) -> ChatRecordPageDTO:
        del query
        self._fail("list_records")

    async def list_user_events(
        self,
        query: ChatUserEventQueryDTO,
    ) -> ChatUserEventPageDTO:
        del query
        self._fail("list_user_events")

    async def get_user_event_tail(self, user_id: str) -> ChatUserEventTailDTO:
        del user_id
        self._fail("get_user_event_tail")

    async def advance_delivery(
        self,
        command: ChatPositionAdvanceDTO,
    ) -> ChatReceiptPositionDTO:
        del command
        self._fail("advance_delivery")

    async def advance_read(
        self,
        command: ChatPositionAdvanceDTO,
    ) -> ChatReceiptPositionDTO:
        del command
        self._fail("advance_read")

    async def get_unread_position(
        self,
        query: ChatPositionQueryDTO,
    ) -> ChatUnreadPositionDTO:
        del query
        self._fail("get_unread_position")

    async def get_resume_position(
        self,
        query: ChatPositionQueryDTO,
    ) -> ChatResumePositionDTO:
        del query
        self._fail("get_resume_position")

    async def delete_records(
        self,
        command: ChatRecordDeleteCommandDTO,
    ) -> ChatRecordMutationResultDTO:
        del command
        self._fail("delete_records")

    async def apply_retention(
        self,
        command: ChatRetentionCommandDTO,
    ) -> ChatRecordMutationResultDTO:
        del command
        self._fail("apply_retention")


@final
class UnconfiguredChatAssetStore(_UnconfiguredStore):
    """Default asset store; rejects every intent and lifecycle operation."""

    __slots__ = ()

    store_name: Literal["chat_asset_store"] = "chat_asset_store"

    @property
    def capability(self) -> StorageCapabilityDescription:
        return CHAT_ASSET_STORAGE_UNCONFIGURED

    async def create_upload_intent(
        self,
        metadata: ChatAssetUploadMetadataDTO,
    ) -> ChatAssetUploadHandleDTO:
        del metadata
        self._fail("create_upload_intent")

    async def finalize_upload(
        self,
        handle: ChatAssetUploadHandleDTO,
    ) -> ChatAssetDTO:
        del handle
        self._fail("finalize_upload")

    async def create_download_intent(
        self,
        asset_id: str,
    ) -> ChatAssetDownloadIntentDTO:
        del asset_id
        self._fail("create_download_intent")

    async def quarantine_asset(
        self,
        command: ChatAssetQuarantineCommandDTO,
    ) -> ChatAssetDTO:
        del command
        self._fail("quarantine_asset")

    async def delete_asset(self, command: ChatAssetDeleteCommandDTO) -> None:
        del command
        self._fail("delete_asset")


UNCONFIGURED_CHAT_RECORD_STORE: ChatRecordStore = UnconfiguredChatRecordStore()
UNCONFIGURED_CHAT_ASSET_STORE: ChatAssetStore = UnconfiguredChatAssetStore()


def get_c19_storage_capabilities() -> C19StorageCapabilities:
    """Return safe control-plane capability metadata without external I/O."""

    # Local import avoids a module cycle: the HTTP adapter implements the
    # protocol declared here.  Configuration parsing opens no socket/client.
    from .http_record_store import (
        HttpChatRecordStoreConfig,
        configured_chat_record_capability,
    )

    try:
        config = HttpChatRecordStoreConfig.from_environment()
    except (TypeError, ValueError, OverflowError):
        config = None
    record_capability = (
        configured_chat_record_capability()
        if config is not None
        else CHAT_RECORD_STORAGE_UNCONFIGURED
    )
    return C19StorageCapabilities(
        record_store=record_capability,
        asset_store=CHAT_ASSET_STORAGE_UNCONFIGURED,
    )


StorageUnconfiguredError = C19StorageUnconfiguredError


__all__ = [
    "C19_STORAGE_CAPABILITIES",
    "CHAT_ASSET_STORAGE_UNCONFIGURED",
    "CHAT_ASSET_STORE_OPERATIONS",
    "CHAT_RECORD_STORAGE_UNCONFIGURED",
    "CHAT_RECORD_STORE_OPERATIONS",
    "UNCONFIGURED_CHAT_ASSET_STORE",
    "UNCONFIGURED_CHAT_RECORD_STORE",
    "C19StorageCapabilities",
    "C19StorageUnconfiguredError",
    "ChatAssetDTO",
    "ChatAssetDeleteCommandDTO",
    "ChatAssetDownloadIntentDTO",
    "ChatAssetQuarantineCommandDTO",
    "ChatAssetReferenceDTO",
    "ChatAssetStore",
    "ChatAssetUploadHandleDTO",
    "ChatAssetUploadMetadataDTO",
    "ChatPositionAdvanceDTO",
    "ChatPositionQueryDTO",
    "ChatReceiptPositionDTO",
    "ChatRecordAppendDTO",
    "ChatRecordDTO",
    "ChatRecordDeleteCommandDTO",
    "ChatRecordMutationResultDTO",
    "ChatRecordPageDTO",
    "ChatRecordQueryDTO",
    "ChatRecordStore",
    "ChatResumePositionDTO",
    "ChatRetentionCommandDTO",
    "ChatUnreadPositionDTO",
    "ChatUserEventDTO",
    "ChatUserEventPageDTO",
    "ChatUserEventQueryDTO",
    "ChatUserEventTailDTO",
    "StorageCapabilityDescription",
    "StorageUnconfiguredError",
    "UnconfiguredChatAssetStore",
    "UnconfiguredChatRecordStore",
    "get_c19_storage_capabilities",
]
