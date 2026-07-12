"""Provider-neutral Stage 5 Moments contracts.

Moment bodies and social interactions belong to the independent Record Service.
Moment image bytes and lifecycle belong to the independent Asset Service.  This
module contains DTOs and fail-closed ports only; it performs no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, NoReturn, Protocol, final, runtime_checkable

from .storage import (
    ChatAssetDisposition,
    ChatAssetDownloadIntentDTO,
    ChatAssetLifecycleResultDTO,
    ChatAssetReferenceDTO,
    ChatAssetStatus,
    ChatAssetTransferDirection,
    ChatAssetTransferMethod,
    ChatAssetVariant,
    C19StorageUnconfiguredError,
    StorageCapabilityDescription,
)


MomentVisibility = Literal["public", "org", "friends", "private"]
MomentState = Literal["draft", "published", "delete_pending", "deleted"]
MomentCommentState = Literal["active", "deleted"]
MomentEventType = Literal[
    "published",
    "deleted",
    "liked",
    "unliked",
    "commented",
    "comment_deleted",
]
MomentAssetUsage = Literal["chat_message", "moment_image"]

MOMENT_STORE_OPERATIONS = (
    "reserve_moment",
    "get_moment_draft",
    "publish_moment",
    "get_moment",
    "list_moment_feed",
    "set_moment_like",
    "list_moment_likes",
    "create_moment_comment",
    "list_moment_comments",
    "delete_moment_comment",
    "begin_moment_delete",
    "complete_moment_delete",
    "list_moment_events",
    "get_moment_event_tail",
)

MOMENT_ASSET_STORE_OPERATIONS = (
    "create_moment_upload_intent",
    "get_moment_asset",
    "finalize_moment_upload",
    "prepare_moment_binding",
    "commit_moment_binding",
    "create_moment_download_intent",
    "inspect_scoped_transfer",
)


@dataclass(frozen=True, slots=True)
class MomentViewerContextDTO:
    viewer_user_id: str
    active_user_ids: tuple[str, ...]
    active_org_ids: tuple[str, ...]
    friend_user_ids: tuple[str, ...]
    blocked_user_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MomentDraftReserveDTO:
    client_moment_id: str
    author_user_id: str


@dataclass(frozen=True, slots=True)
class MomentDraftDTO:
    moment_id: str
    client_moment_id: str
    author_user_id: str
    state: Literal["draft", "published", "delete_pending", "deleted"]
    created_at: datetime
    persisted_at: datetime


@dataclass(frozen=True, slots=True)
class MomentPublishDTO:
    moment_id: str
    client_moment_id: str
    author_user_id: str
    author_org_id: str | None
    visibility: MomentVisibility
    audience_user_ids: tuple[str, ...]
    audience_org_ids: tuple[str, ...]
    content: str
    assets: tuple[ChatAssetReferenceDTO, ...] = ()


@dataclass(frozen=True, slots=True)
class MomentDTO:
    moment_id: str
    client_moment_id: str
    author_user_id: str
    author_org_id: str | None
    visibility: MomentVisibility
    audience_org_ids: tuple[str, ...]
    content: str
    state: MomentState
    created_at: datetime
    published_at: datetime | None
    assets: tuple[ChatAssetReferenceDTO, ...]
    like_count: int
    comment_count: int
    viewer_has_liked: bool


@dataclass(frozen=True, slots=True)
class MomentQueryDTO:
    context: MomentViewerContextDTO
    moment_id: str


@dataclass(frozen=True, slots=True)
class MomentFeedQueryDTO:
    context: MomentViewerContextDTO
    limit: int = 20
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class MomentFeedPageDTO:
    moments: tuple[MomentDTO, ...]
    next_cursor: str | None
    latest_event_sequence: int


@dataclass(frozen=True, slots=True)
class MomentLikeCommandDTO:
    context: MomentViewerContextDTO
    moment_id: str
    liked: bool
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class MomentLikeResultDTO:
    moment_id: str
    user_id: str
    liked: bool
    changed: bool
    like_count: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MomentLikeDTO:
    user_id: str
    sequence: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MomentLikeQueryDTO:
    context: MomentViewerContextDTO
    moment_id: str
    limit: int = 50
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class MomentLikePageDTO:
    likes: tuple[MomentLikeDTO, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class MomentCommentCreateDTO:
    context: MomentViewerContextDTO
    moment_id: str
    client_comment_id: str
    author_user_id: str
    content: str


@dataclass(frozen=True, slots=True)
class MomentCommentDTO:
    comment_id: str
    client_comment_id: str
    moment_id: str
    author_user_id: str
    content: str
    state: MomentCommentState
    sequence: int
    created_at: datetime
    persisted_at: datetime


@dataclass(frozen=True, slots=True)
class MomentCommentQueryDTO:
    context: MomentViewerContextDTO
    moment_id: str
    limit: int = 50
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class MomentCommentPageDTO:
    comments: tuple[MomentCommentDTO, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class MomentCommentDeleteDTO:
    context: MomentViewerContextDTO
    moment_id: str
    comment_id: str
    requested_by_user_id: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class MomentCommentDeleteResultDTO:
    moment_id: str
    comment_id: str
    state: Literal["deleted"]
    changed: bool
    comment_count: int
    deleted_at: datetime


@dataclass(frozen=True, slots=True)
class MomentDeleteCommandDTO:
    context: MomentViewerContextDTO
    moment_id: str
    requested_by_user_id: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class MomentDeleteResultDTO:
    moment_id: str
    state: Literal["delete_pending", "deleted"]
    assets: tuple[ChatAssetReferenceDTO, ...]
    changed: bool
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MomentUserEventDTO:
    event_id: str
    user_id: str
    event_sequence: int
    event_type: MomentEventType
    moment_id: str
    actor_user_id: str
    comment_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MomentUserEventQueryDTO:
    context: MomentViewerContextDTO
    limit: int = 100
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class MomentUserEventPageDTO:
    events: tuple[MomentUserEventDTO, ...]
    next_cursor: str | None
    latest_event_sequence: int


@dataclass(frozen=True, slots=True)
class MomentUserEventTailDTO:
    user_id: str
    cursor: str
    latest_event_sequence: int


@dataclass(frozen=True, slots=True)
class MomentAssetDTO:
    asset_id: str
    client_asset_id: str
    owner_user_id: str
    moment_id: str
    kind: Literal["image"]
    filename: str
    media_type: str
    size_bytes: int
    sha256_hex: str
    version: int
    status: ChatAssetStatus


@dataclass(frozen=True, slots=True)
class MomentAssetUploadMetadataDTO:
    client_asset_id: str
    owner_user_id: str
    moment_id: str
    filename: str
    media_type: str
    size_bytes: int
    sha256_hex: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class MomentAssetUploadHandleDTO:
    asset: MomentAssetDTO
    opaque_ticket: str | None
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class MomentAssetLookupDTO:
    asset_id: str
    owner_user_id: str
    moment_id: str


@dataclass(frozen=True, slots=True)
class MomentAssetFinalizeDTO:
    asset_id: str
    owner_user_id: str
    moment_id: str


@dataclass(frozen=True, slots=True)
class MomentAssetBindingPrepareDTO:
    asset_id: str
    owner_user_id: str
    moment_id: str
    client_moment_id: str


@dataclass(frozen=True, slots=True)
class MomentAssetBindingCommitDTO:
    asset_id: str
    owner_user_id: str
    moment_id: str
    client_moment_id: str


@dataclass(frozen=True, slots=True)
class MomentAssetBindingResultDTO:
    asset: MomentAssetDTO
    binding_status: Literal["prepared", "committed"]


@dataclass(frozen=True, slots=True)
class MomentAssetDownloadRequestDTO:
    asset_id: str
    owner_user_id: str
    reader_user_id: str
    moment_id: str
    variant: ChatAssetVariant
    disposition: ChatAssetDisposition
    asset_version: int


@dataclass(frozen=True, slots=True)
class ScopedAssetTransferInspectionDTO:
    asset_id: str
    owner_user_id: str
    reader_user_id: str | None
    usage: MomentAssetUsage
    scope_id: str
    bound_resource_id: str | None
    variant: ChatAssetVariant | None
    version: int
    expires_at: datetime


@runtime_checkable
class MomentStore(Protocol):
    @property
    def capability(self) -> StorageCapabilityDescription: ...

    async def reserve_moment(self, command: MomentDraftReserveDTO) -> MomentDraftDTO: ...

    async def get_moment_draft(self, *, moment_id: str, author_user_id: str) -> MomentDraftDTO: ...

    async def publish_moment(self, command: MomentPublishDTO) -> MomentDTO: ...

    async def get_moment(self, query: MomentQueryDTO) -> MomentDTO: ...

    async def list_moment_feed(self, query: MomentFeedQueryDTO) -> MomentFeedPageDTO: ...

    async def set_moment_like(self, command: MomentLikeCommandDTO) -> MomentLikeResultDTO: ...

    async def list_moment_likes(self, query: MomentLikeQueryDTO) -> MomentLikePageDTO: ...

    async def create_moment_comment(self, command: MomentCommentCreateDTO) -> MomentCommentDTO: ...

    async def list_moment_comments(self, query: MomentCommentQueryDTO) -> MomentCommentPageDTO: ...

    async def delete_moment_comment(self, command: MomentCommentDeleteDTO) -> MomentCommentDeleteResultDTO: ...

    async def begin_moment_delete(self, command: MomentDeleteCommandDTO) -> MomentDeleteResultDTO: ...

    async def complete_moment_delete(self, command: MomentDeleteCommandDTO) -> MomentDeleteResultDTO: ...

    async def list_moment_events(self, query: MomentUserEventQueryDTO) -> MomentUserEventPageDTO: ...

    async def get_moment_event_tail(
        self,
        context: MomentViewerContextDTO,
    ) -> MomentUserEventTailDTO: ...


@runtime_checkable
class MomentAssetStore(Protocol):
    @property
    def capability(self) -> StorageCapabilityDescription: ...

    async def create_moment_upload_intent(self, metadata: MomentAssetUploadMetadataDTO) -> MomentAssetUploadHandleDTO: ...

    async def get_moment_asset(self, query: MomentAssetLookupDTO) -> MomentAssetDTO: ...

    async def finalize_moment_upload(self, command: MomentAssetFinalizeDTO) -> MomentAssetDTO: ...

    async def prepare_moment_binding(self, command: MomentAssetBindingPrepareDTO) -> MomentAssetBindingResultDTO: ...

    async def commit_moment_binding(self, command: MomentAssetBindingCommitDTO) -> MomentAssetBindingResultDTO: ...

    async def create_moment_download_intent(self, command: MomentAssetDownloadRequestDTO) -> ChatAssetDownloadIntentDTO: ...

    async def inspect_scoped_transfer(
        self,
        *,
        opaque_ticket: str,
        direction: ChatAssetTransferDirection,
        method: ChatAssetTransferMethod,
    ) -> ScopedAssetTransferInspectionDTO: ...

    async def delete_asset(self, command: object) -> ChatAssetLifecycleResultDTO: ...


class _UnconfiguredMomentPort:
    store_name: Literal["chat_record_store", "chat_asset_store"]

    def _fail(self, operation: str) -> NoReturn:
        raise C19StorageUnconfiguredError(
            store_name=self.store_name,
            operation=operation,
        )


@final
class UnconfiguredMomentStore(_UnconfiguredMomentPort):
    store_name: Literal["chat_record_store"] = "chat_record_store"

    @property
    def capability(self) -> StorageCapabilityDescription:
        return StorageCapabilityDescription(
            store_name="chat_record_store",
            status="unconfigured",
            configured=False,
            readable=False,
            writable=False,
            durable=False,
            external_io_enabled=False,
            operations=MOMENT_STORE_OPERATIONS,
            reason="No vetted C19 Moment record provider is configured.",
        )

    async def reserve_moment(self, command: MomentDraftReserveDTO) -> MomentDraftDTO:
        del command
        self._fail("reserve_moment")

    async def get_moment_draft(
        self,
        *,
        moment_id: str,
        author_user_id: str,
    ) -> MomentDraftDTO:
        del moment_id, author_user_id
        self._fail("get_moment_draft")

    async def publish_moment(self, command: MomentPublishDTO) -> MomentDTO:
        del command
        self._fail("publish_moment")

    async def get_moment(self, query: MomentQueryDTO) -> MomentDTO:
        del query
        self._fail("get_moment")

    async def list_moment_feed(
        self,
        query: MomentFeedQueryDTO,
    ) -> MomentFeedPageDTO:
        del query
        self._fail("list_moment_feed")

    async def set_moment_like(
        self,
        command: MomentLikeCommandDTO,
    ) -> MomentLikeResultDTO:
        del command
        self._fail("set_moment_like")

    async def list_moment_likes(
        self,
        query: MomentLikeQueryDTO,
    ) -> MomentLikePageDTO:
        del query
        self._fail("list_moment_likes")

    async def create_moment_comment(
        self,
        command: MomentCommentCreateDTO,
    ) -> MomentCommentDTO:
        del command
        self._fail("create_moment_comment")

    async def list_moment_comments(
        self,
        query: MomentCommentQueryDTO,
    ) -> MomentCommentPageDTO:
        del query
        self._fail("list_moment_comments")

    async def delete_moment_comment(
        self,
        command: MomentCommentDeleteDTO,
    ) -> MomentCommentDeleteResultDTO:
        del command
        self._fail("delete_moment_comment")

    async def begin_moment_delete(
        self,
        command: MomentDeleteCommandDTO,
    ) -> MomentDeleteResultDTO:
        del command
        self._fail("begin_moment_delete")

    async def complete_moment_delete(
        self,
        command: MomentDeleteCommandDTO,
    ) -> MomentDeleteResultDTO:
        del command
        self._fail("complete_moment_delete")

    async def list_moment_events(
        self,
        query: MomentUserEventQueryDTO,
    ) -> MomentUserEventPageDTO:
        del query
        self._fail("list_moment_events")

    async def get_moment_event_tail(
        self,
        context: MomentViewerContextDTO,
    ) -> MomentUserEventTailDTO:
        del context
        self._fail("get_moment_event_tail")


@final
class UnconfiguredMomentAssetStore(_UnconfiguredMomentPort):
    store_name: Literal["chat_asset_store"] = "chat_asset_store"

    @property
    def capability(self) -> StorageCapabilityDescription:
        return StorageCapabilityDescription(
            store_name="chat_asset_store",
            status="unconfigured",
            configured=False,
            readable=False,
            writable=False,
            durable=False,
            external_io_enabled=False,
            operations=MOMENT_ASSET_STORE_OPERATIONS + ("delete_asset",),
            reason="No vetted C19 Moment asset provider is configured.",
        )

    async def create_moment_upload_intent(
        self,
        metadata: MomentAssetUploadMetadataDTO,
    ) -> MomentAssetUploadHandleDTO:
        del metadata
        self._fail("create_moment_upload_intent")

    async def get_moment_asset(
        self,
        query: MomentAssetLookupDTO,
    ) -> MomentAssetDTO:
        del query
        self._fail("get_moment_asset")

    async def finalize_moment_upload(
        self,
        command: MomentAssetFinalizeDTO,
    ) -> MomentAssetDTO:
        del command
        self._fail("finalize_moment_upload")

    async def prepare_moment_binding(
        self,
        command: MomentAssetBindingPrepareDTO,
    ) -> MomentAssetBindingResultDTO:
        del command
        self._fail("prepare_moment_binding")

    async def commit_moment_binding(
        self,
        command: MomentAssetBindingCommitDTO,
    ) -> MomentAssetBindingResultDTO:
        del command
        self._fail("commit_moment_binding")

    async def create_moment_download_intent(
        self,
        command: MomentAssetDownloadRequestDTO,
    ) -> ChatAssetDownloadIntentDTO:
        del command
        self._fail("create_moment_download_intent")

    async def inspect_scoped_transfer(
        self,
        *,
        opaque_ticket: str,
        direction: ChatAssetTransferDirection,
        method: ChatAssetTransferMethod,
    ) -> ScopedAssetTransferInspectionDTO:
        del opaque_ticket, direction, method
        self._fail("inspect_scoped_transfer")

    async def delete_asset(
        self,
        command: object,
    ) -> ChatAssetLifecycleResultDTO:
        del command
        self._fail("delete_asset")


UNCONFIGURED_MOMENT_STORE: MomentStore = UnconfiguredMomentStore()  # type: ignore[assignment]
UNCONFIGURED_MOMENT_ASSET_STORE: MomentAssetStore = UnconfiguredMomentAssetStore()  # type: ignore[assignment]


__all__ = [
    name
    for name in globals()
    if name.startswith("Moment")
    or name.startswith("Scoped")
    or name.startswith("MOMENT_")
    or name.startswith("UNCONFIGURED_MOMENT_")
]
