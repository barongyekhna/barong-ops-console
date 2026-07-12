"""HTTP adapter for the independently deployable C19 record service.

The adapter owns no message persistence.  It translates the provider-neutral
``ChatRecordStore`` contract into the versioned record-service API and rejects
missing, unreachable, or malformed providers without manufacturing a success.
"""

from __future__ import annotations

import os
import re
from ipaddress import ip_address
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, NoReturn
from urllib.parse import quote, urlsplit

import httpx

from .moment_storage import (
    MOMENT_STORE_OPERATIONS,
    MomentCommentCreateDTO,
    MomentCommentDeleteDTO,
    MomentCommentDeleteResultDTO,
    MomentCommentDTO,
    MomentCommentPageDTO,
    MomentCommentQueryDTO,
    MomentDTO,
    MomentDeleteCommandDTO,
    MomentDeleteResultDTO,
    MomentDraftDTO,
    MomentDraftReserveDTO,
    MomentFeedPageDTO,
    MomentFeedQueryDTO,
    MomentLikeCommandDTO,
    MomentLikeDTO,
    MomentLikePageDTO,
    MomentLikeQueryDTO,
    MomentLikeResultDTO,
    MomentPublishDTO,
    MomentQueryDTO,
    MomentUserEventDTO,
    MomentUserEventPageDTO,
    MomentUserEventQueryDTO,
    MomentUserEventTailDTO,
    MomentViewerContextDTO,
)
from .storage import (
    CHAT_RECORD_STORE_OPERATIONS,
    ChatAssetReferenceDTO,
    ChatPositionAdvanceDTO,
    ChatPositionQueryDTO,
    ChatReceiptPositionDTO,
    ChatRecordAppendDTO,
    ChatRecordDTO,
    ChatRecordDeleteCommandDTO,
    ChatRecordMutationResultDTO,
    ChatRecordPageDTO,
    ChatRecordQueryDTO,
    ChatResumePositionDTO,
    ChatRetentionBatchCommandDTO,
    ChatRetentionBatchResultDTO,
    ChatUnreadPositionDTO,
    ChatUnreadSummaryDTO,
    ChatUnreadSummaryQueryDTO,
    ChatUserEventDTO,
    ChatUserEventPageDTO,
    ChatUserEventQueryDTO,
    ChatUserEventTailDTO,
    StorageCapabilityDescription,
)


RECORD_STORE_URL_ENV = "C19_RECORD_STORE_URL"
RECORD_STORE_TOKEN_ENV = "C19_RECORD_STORE_TOKEN"
RECORD_STORE_TIMEOUT_ENV = "C19_RECORD_STORE_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_TIMEOUT_SECONDS = 60.0


class ChatRecordStoreHttpError(RuntimeError):
    """Stable, content-free error surfaced by the HTTP adapter."""

    code = "c19_record_store_error"
    retryable = False

    def __init__(
        self,
        *,
        operation: str,
        status_code: int | None = None,
    ) -> None:
        self.operation = operation
        self.status_code = status_code
        super().__init__(f"C19 record store operation failed: {self.code}.")


class ChatRecordStoreUnavailableError(ChatRecordStoreHttpError):
    code = "c19_record_store_unavailable"
    retryable = True


class ChatRecordStoreAuthenticationError(ChatRecordStoreHttpError):
    code = "c19_record_store_authentication_failed"


class ChatRecordStoreConflictError(ChatRecordStoreHttpError):
    code = "c19_record_store_conflict"


class ChatRecordStoreRejectedError(ChatRecordStoreHttpError):
    code = "c19_record_store_request_rejected"


class ChatRecordStoreProtocolError(ChatRecordStoreHttpError):
    code = "c19_record_store_invalid_response"


@dataclass(frozen=True, slots=True)
class HttpChatRecordStoreConfig:
    """Non-database client configuration; token representation is redacted."""

    base_url: str
    token: str = field(repr=False)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        normalized_url = self.base_url.strip().rstrip("/")
        parsed = urlsplit(normalized_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("C19 record store URL is invalid.")
        if parsed.scheme == "http":
            hostname = parsed.hostname.lower()
            try:
                address = ip_address(hostname)
                private_http = (
                    address.is_private
                    or address.is_loopback
                    or address.is_link_local
                )
            except ValueError:
                private_http = "." not in hostname
            if not private_http:
                raise ValueError(
                    "C19 record store HTTP is allowed only on a private host."
                )
        if len(self.token) < 32 or self.token != self.token.strip():
            raise ValueError("C19 record store token is invalid.")
        if not (0 < float(self.timeout_seconds) <= MAX_TIMEOUT_SECONDS):
            raise ValueError("C19 record store timeout is invalid.")
        object.__setattr__(self, "base_url", normalized_url)
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> HttpChatRecordStoreConfig | None:
        values = os.environ if environ is None else environ
        base_url = values.get(RECORD_STORE_URL_ENV, "").strip()
        token = values.get(RECORD_STORE_TOKEN_ENV, "")
        if not base_url or not token:
            return None
        timeout_raw = values.get(RECORD_STORE_TIMEOUT_ENV, "").strip()
        timeout = DEFAULT_TIMEOUT_SECONDS if not timeout_raw else float(timeout_raw)
        return cls(base_url=base_url, token=token, timeout_seconds=timeout)


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("C19 record timestamps must be timezone-aware.")
    return value.isoformat()


def _mapping(
    value: Any,
    *,
    operation: str,
    exact_keys: frozenset[str] | None = None,
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ChatRecordStoreProtocolError(operation=operation)
    if exact_keys is not None and frozenset(value) != exact_keys:
        raise ChatRecordStoreProtocolError(operation=operation)
    return value


def _required_string(
    data: Mapping[str, Any],
    key: str,
    *,
    operation: str,
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ChatRecordStoreProtocolError(operation=operation)
    return value


def _optional_string(
    data: Mapping[str, Any],
    key: str,
    *,
    operation: str,
) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ChatRecordStoreProtocolError(operation=operation)
    return value


def _integer(
    data: Mapping[str, Any],
    key: str,
    *,
    operation: str,
    minimum: int = 0,
) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ChatRecordStoreProtocolError(operation=operation)
    return value


def _boolean(
    data: Mapping[str, Any],
    key: str,
    *,
    operation: str,
) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ChatRecordStoreProtocolError(operation=operation)
    return value


def _timestamp(
    data: Mapping[str, Any],
    key: str,
    *,
    operation: str,
) -> datetime:
    raw = _required_string(data, key, operation=operation)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ChatRecordStoreProtocolError(operation=operation) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ChatRecordStoreProtocolError(operation=operation)
    return parsed


def _string_tuple(
    data: Mapping[str, Any],
    key: str,
    *,
    operation: str,
) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ChatRecordStoreProtocolError(operation=operation)
    return tuple(value)


def _metadata_tuple(
    data: Mapping[str, Any],
    *,
    operation: str,
) -> tuple[tuple[str, str], ...]:
    value = data.get("metadata", {})
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in value.items()
    ):
        raise ChatRecordStoreProtocolError(operation=operation)
    return tuple(sorted(value.items()))


_ASSET_ID_RE = re.compile(r"^att_[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ASSET_REFERENCE_KEYS = frozenset(
    {
        "asset_id",
        "client_asset_id",
        "kind",
        "filename",
        "media_type",
        "size_bytes",
        "sha256_hex",
        "version",
        "ordinal",
    }
)
_IMAGE_MEDIA_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif"}
)
_FILE_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "text/plain",
        "text/csv",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/zip",
    }
)
_RECORD_KEYS = frozenset(
    {
        "record_id",
        "client_message_id",
        "conversation_id",
        "sequence",
        "sender_user_id",
        "recipient_user_ids",
        "content_type",
        "content",
        "status",
        "created_at",
        "persisted_at",
        "sender_org_id",
        "recipient_org_ids",
        "metadata",
        "assets",
    }
)


def _assets_tuple(
    data: Mapping[str, Any],
    *,
    operation: str,
    maximum: int = 1,
    image_only: bool = False,
) -> tuple[ChatAssetReferenceDTO, ...]:
    value = data.get("assets", [])
    if not isinstance(value, list) or len(value) > maximum:
        raise ChatRecordStoreProtocolError(operation=operation)
    assets: list[ChatAssetReferenceDTO] = []
    for raw in value:
        item = _mapping(raw, operation=operation)
        if frozenset(item) != _ASSET_REFERENCE_KEYS:
            raise ChatRecordStoreProtocolError(operation=operation)
        asset_id = _required_string(item, "asset_id", operation=operation)
        client_asset_id = _required_string(
            item, "client_asset_id", operation=operation
        )
        sha256_hex = _required_string(item, "sha256_hex", operation=operation)
        kind = _required_string(item, "kind", operation=operation)
        filename = _required_string(item, "filename", operation=operation)
        media_type = _required_string(item, "media_type", operation=operation)
        size_bytes = _integer(item, "size_bytes", operation=operation, minimum=1)
        if (
            _ASSET_ID_RE.fullmatch(asset_id) is None
            or _SHA256_RE.fullmatch(sha256_hex) is None
            or kind not in {"image", "file"}
            or len(client_asset_id) > 128
            or len(filename) > 255
            or filename in {".", ".."}
            or "/" in filename
            or "\\" in filename
            or any(ord(character) < 32 for character in filename)
            or media_type != media_type.lower()
            or size_bytes > 64 * 1024 * 1024
            or (kind == "image" and media_type not in _IMAGE_MEDIA_TYPES)
            or (kind == "file" and media_type not in _FILE_MEDIA_TYPES)
            or (image_only and kind != "image")
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        assets.append(
            ChatAssetReferenceDTO(
                asset_id=asset_id,
                client_asset_id=client_asset_id,
                kind=kind,  # type: ignore[arg-type]
                filename=filename,
                media_type=media_type,
                size_bytes=size_bytes,
                sha256_hex=sha256_hex,
                version=_integer(item, "version", operation=operation, minimum=1),
                ordinal=_integer(item, "ordinal", operation=operation),
            )
        )
    if [asset.ordinal for asset in assets] != list(range(len(assets))):
        raise ChatRecordStoreProtocolError(operation=operation)
    return tuple(assets)


def _record_from_json(data: Any, *, operation: str) -> ChatRecordDTO:
    item = _mapping(data, operation=operation)
    if not frozenset(item).issubset(_RECORD_KEYS):
        raise ChatRecordStoreProtocolError(operation=operation)
    status = _required_string(item, "status", operation=operation)
    if status not in {"sent", "delivered", "read"}:
        raise ChatRecordStoreProtocolError(operation=operation)
    content_type = _required_string(item, "content_type", operation=operation)
    if content_type not in {"text", "emoji", "image", "file"}:
        raise ChatRecordStoreProtocolError(operation=operation)
    content = item.get("content")
    if (
        not isinstance(content, str)
        or len(content) > 4000
        or any(
            ord(character) < 32 and character not in {"\n", "\t"}
            for character in content
        )
    ):
        raise ChatRecordStoreProtocolError(operation=operation)
    assets = _assets_tuple(item, operation=operation)
    if (
        (content_type in {"image", "file"}) != (len(assets) == 1)
        or (content_type in {"text", "emoji"} and not content.strip())
        or (
            content_type == "emoji"
            and (len(content) > 64 or "\n" in content or "\t" in content)
        )
        or (assets and assets[0].kind != content_type)
    ):
        raise ChatRecordStoreProtocolError(operation=operation)
    return ChatRecordDTO(
        record_id=_required_string(item, "record_id", operation=operation),
        client_message_id=_required_string(
            item,
            "client_message_id",
            operation=operation,
        ),
        conversation_id=_required_string(
            item,
            "conversation_id",
            operation=operation,
        ),
        sequence=_integer(item, "sequence", operation=operation, minimum=1),
        sender_user_id=_required_string(
            item,
            "sender_user_id",
            operation=operation,
        ),
        recipient_user_ids=_string_tuple(
            item,
            "recipient_user_ids",
            operation=operation,
        ),
        content_type=content_type,
        content=content,
        status=status,  # type: ignore[arg-type]
        created_at=_timestamp(item, "created_at", operation=operation),
        persisted_at=_timestamp(item, "persisted_at", operation=operation),
        sender_org_id=_optional_string(
            item,
            "sender_org_id",
            operation=operation,
        ),
        recipient_org_ids=_string_tuple(
            item,
            "recipient_org_ids",
            operation=operation,
        ),
        metadata=_metadata_tuple(item, operation=operation),
        assets=assets,
    )


def _receipt_from_json(data: Any, *, operation: str) -> ChatReceiptPositionDTO:
    item = _mapping(data, operation=operation)
    return ChatReceiptPositionDTO(
        conversation_id=_required_string(
            item,
            "conversation_id",
            operation=operation,
        ),
        user_id=_required_string(item, "user_id", operation=operation),
        delivered_through_sequence=_integer(
            item,
            "delivered_through_sequence",
            operation=operation,
        ),
        read_through_sequence=_integer(
            item,
            "read_through_sequence",
            operation=operation,
        ),
        updated_at=_timestamp(item, "updated_at", operation=operation),
    )


_MOMENT_ID_RE = re.compile(r"^mom_[0-9a-f]{32}$")
_COMMENT_ID_RE = re.compile(r"^cmt_[0-9a-f]{32}$")
_DRAFT_KEYS = frozenset(
    {
        "moment_id",
        "client_moment_id",
        "author_user_id",
        "state",
        "created_at",
        "persisted_at",
    }
)
_MOMENT_KEYS = frozenset(
    {
        "moment_id",
        "client_moment_id",
        "author_user_id",
        "author_org_id",
        "visibility",
        "audience_org_ids",
        "content",
        "state",
        "created_at",
        "published_at",
        "assets",
        "like_count",
        "comment_count",
        "viewer_has_liked",
    }
)


def _draft_from_json(data: Any, *, operation: str) -> MomentDraftDTO:
    item = _mapping(data, operation=operation, exact_keys=_DRAFT_KEYS)
    moment_id = _required_string(item, "moment_id", operation=operation)
    state = _required_string(item, "state", operation=operation)
    if (
        _MOMENT_ID_RE.fullmatch(moment_id) is None
        or state not in {"draft", "published", "delete_pending", "deleted"}
    ):
        raise ChatRecordStoreProtocolError(operation=operation)
    return MomentDraftDTO(
        moment_id=moment_id,
        client_moment_id=_required_string(
            item,
            "client_moment_id",
            operation=operation,
        ),
        author_user_id=_required_string(
            item,
            "author_user_id",
            operation=operation,
        ),
        state=state,  # type: ignore[arg-type]
        created_at=_timestamp(item, "created_at", operation=operation),
        persisted_at=_timestamp(item, "persisted_at", operation=operation),
    )


def _moment_from_json(data: Any, *, operation: str) -> MomentDTO:
    item = _mapping(data, operation=operation, exact_keys=_MOMENT_KEYS)
    moment_id = _required_string(item, "moment_id", operation=operation)
    visibility = _required_string(item, "visibility", operation=operation)
    state = _required_string(item, "state", operation=operation)
    content = item.get("content")
    audience_org_ids = _string_tuple(
        item,
        "audience_org_ids",
        operation=operation,
    )
    if (
        _MOMENT_ID_RE.fullmatch(moment_id) is None
        or visibility not in {"public", "org", "friends", "private"}
        or state != "published"
        or not isinstance(content, str)
        or len(content) > 4000
        or any(
            ord(character) < 32 and character not in {"\n", "\t"}
            for character in content
        )
        or len(audience_org_ids) > 32
        or len(audience_org_ids) != len(set(audience_org_ids))
        or (visibility == "org") != bool(audience_org_ids)
    ):
        raise ChatRecordStoreProtocolError(operation=operation)
    return MomentDTO(
        moment_id=moment_id,
        client_moment_id=_required_string(
            item,
            "client_moment_id",
            operation=operation,
        ),
        author_user_id=_required_string(
            item,
            "author_user_id",
            operation=operation,
        ),
        author_org_id=_optional_string(
            item,
            "author_org_id",
            operation=operation,
        ),
        visibility=visibility,  # type: ignore[arg-type]
        audience_org_ids=audience_org_ids,
        content=content,
        state="published",
        created_at=_timestamp(item, "created_at", operation=operation),
        published_at=_timestamp(item, "published_at", operation=operation),
        assets=_assets_tuple(
            item,
            operation=operation,
            maximum=9,
            image_only=True,
        ),
        like_count=_integer(item, "like_count", operation=operation),
        comment_count=_integer(item, "comment_count", operation=operation),
        viewer_has_liked=_boolean(
            item,
            "viewer_has_liked",
            operation=operation,
        ),
    )


def _like_result_from_json(data: Any, *, operation: str) -> MomentLikeResultDTO:
    item = _mapping(
        data,
        operation=operation,
        exact_keys=frozenset(
            {
                "moment_id",
                "user_id",
                "liked",
                "changed",
                "like_count",
                "updated_at",
            }
        ),
    )
    moment_id = _required_string(item, "moment_id", operation=operation)
    if _MOMENT_ID_RE.fullmatch(moment_id) is None:
        raise ChatRecordStoreProtocolError(operation=operation)
    return MomentLikeResultDTO(
        moment_id=moment_id,
        user_id=_required_string(item, "user_id", operation=operation),
        liked=_boolean(item, "liked", operation=operation),
        changed=_boolean(item, "changed", operation=operation),
        like_count=_integer(item, "like_count", operation=operation),
        updated_at=_timestamp(item, "updated_at", operation=operation),
    )


def _comment_from_json(data: Any, *, operation: str) -> MomentCommentDTO:
    item = _mapping(
        data,
        operation=operation,
        exact_keys=frozenset(
            {
                "comment_id",
                "client_comment_id",
                "moment_id",
                "author_user_id",
                "content",
                "state",
                "sequence",
                "created_at",
                "persisted_at",
            }
        ),
    )
    comment_id = _required_string(item, "comment_id", operation=operation)
    moment_id = _required_string(item, "moment_id", operation=operation)
    state = _required_string(item, "state", operation=operation)
    content = item.get("content")
    if (
        _COMMENT_ID_RE.fullmatch(comment_id) is None
        or _MOMENT_ID_RE.fullmatch(moment_id) is None
        or state != "active"
        or not isinstance(content, str)
        or not content.strip()
        or len(content) > 1000
        or any(
            ord(character) < 32 and character not in {"\n", "\t"}
            for character in content
        )
    ):
        raise ChatRecordStoreProtocolError(operation=operation)
    return MomentCommentDTO(
        comment_id=comment_id,
        client_comment_id=_required_string(
            item,
            "client_comment_id",
            operation=operation,
        ),
        moment_id=moment_id,
        author_user_id=_required_string(
            item,
            "author_user_id",
            operation=operation,
        ),
        content=content,
        state="active",
        sequence=_integer(item, "sequence", operation=operation, minimum=1),
        created_at=_timestamp(item, "created_at", operation=operation),
        persisted_at=_timestamp(item, "persisted_at", operation=operation),
    )


def _delete_result_from_json(
    data: Any,
    *,
    operation: str,
) -> MomentDeleteResultDTO:
    item = _mapping(
        data,
        operation=operation,
        exact_keys=frozenset(
            {"moment_id", "state", "changed", "assets", "updated_at"}
        ),
    )
    moment_id = _required_string(item, "moment_id", operation=operation)
    state = _required_string(item, "state", operation=operation)
    assets = _assets_tuple(
        item,
        operation=operation,
        maximum=9,
        image_only=True,
    )
    if (
        _MOMENT_ID_RE.fullmatch(moment_id) is None
        or state not in {"delete_pending", "deleted"}
        or (state == "deleted" and assets)
    ):
        raise ChatRecordStoreProtocolError(operation=operation)
    return MomentDeleteResultDTO(
        moment_id=moment_id,
        state=state,  # type: ignore[arg-type]
        assets=assets,
        changed=_boolean(item, "changed", operation=operation),
        updated_at=_timestamp(item, "updated_at", operation=operation),
    )


def _moment_event_from_json(
    data: Any,
    *,
    operation: str,
    user_id: str,
) -> MomentUserEventDTO:
    item = _mapping(
        data,
        operation=operation,
        exact_keys=frozenset(
            {
                "event_id",
                "event_sequence",
                "event_type",
                "moment_id",
                "actor_user_id",
                "comment_id",
                "created_at",
            }
        ),
    )
    event_type = _required_string(item, "event_type", operation=operation)
    moment_id = _required_string(item, "moment_id", operation=operation)
    comment_id = _optional_string(item, "comment_id", operation=operation)
    if (
        event_type
        not in {
            "published",
            "deleted",
            "liked",
            "unliked",
            "commented",
            "comment_deleted",
        }
        or _MOMENT_ID_RE.fullmatch(moment_id) is None
        or (
            (event_type in {"commented", "comment_deleted"})
            != (comment_id is not None)
        )
        or (
            comment_id is not None
            and _COMMENT_ID_RE.fullmatch(comment_id) is None
        )
    ):
        raise ChatRecordStoreProtocolError(operation=operation)
    return MomentUserEventDTO(
        event_id=_required_string(item, "event_id", operation=operation),
        user_id=user_id,
        event_sequence=_integer(
            item,
            "event_sequence",
            operation=operation,
            minimum=1,
        ),
        event_type=event_type,  # type: ignore[arg-type]
        moment_id=moment_id,
        actor_user_id=_required_string(
            item,
            "actor_user_id",
            operation=operation,
        ),
        comment_id=comment_id,
        created_at=_timestamp(item, "created_at", operation=operation),
    )


def _context_json(context: MomentViewerContextDTO) -> dict[str, object]:
    return {
        "viewer_user_id": context.viewer_user_id,
        "active_user_ids": list(context.active_user_ids),
        "active_org_ids": list(context.active_org_ids),
        "friend_user_ids": list(context.friend_user_ids),
        "blocked_user_ids": list(context.blocked_user_ids),
    }


class HttpChatRecordStore:
    """Async HTTP implementation with explicit ownership and close semantics."""

    def __init__(
        self,
        config: HttpChatRecordStoreConfig,
        *,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("Provide either an HTTP client or transport, not both.")
        self._config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=f"{config.base_url}/",
            headers={
                "Authorization": f"Bearer {config.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(config.timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    @property
    def capability(self) -> StorageCapabilityDescription:
        return configured_chat_record_capability()

    async def __aenter__(self) -> HttpChatRecordStore:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    def _url(self, path: str) -> str:
        return path.lstrip("/")

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        accepted_statuses: frozenset[int] = frozenset({200}),
    ) -> Any:
        try:
            response = await self._client.request(
                method,
                self._url(path),
                headers={
                    "Authorization": f"Bearer {self._config.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                params=params,
                json=json,
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RequestError):
            raise ChatRecordStoreUnavailableError(operation=operation) from None
        if response.status_code not in accepted_statuses:
            self._raise_response_error(
                operation=operation,
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError:
            raise ChatRecordStoreProtocolError(operation=operation) from None

    @staticmethod
    def _raise_response_error(*, operation: str, status_code: int) -> NoReturn:
        if status_code in {401, 403}:
            raise ChatRecordStoreAuthenticationError(
                operation=operation,
                status_code=status_code,
            )
        if status_code == 409:
            raise ChatRecordStoreConflictError(
                operation=operation,
                status_code=status_code,
            )
        if status_code in {400, 404, 410, 422}:
            raise ChatRecordStoreRejectedError(
                operation=operation,
                status_code=status_code,
            )
        if status_code == 429 or status_code >= 500:
            raise ChatRecordStoreUnavailableError(
                operation=operation,
                status_code=status_code,
            )
        raise ChatRecordStoreProtocolError(
            operation=operation,
            status_code=status_code,
        )

    async def append_record(self, record: ChatRecordAppendDTO) -> ChatRecordDTO:
        operation = "append_record"
        payload = {
            "client_message_id": record.client_message_id,
            "conversation_id": record.conversation_id,
            "sender_user_id": record.sender_user_id,
            "recipient_user_ids": list(record.recipient_user_ids),
            "content_type": record.content_type,
            "content": record.content,
            "created_at": _iso(record.created_at),
            "sender_org_id": record.sender_org_id,
            "recipient_org_ids": list(record.recipient_org_ids),
            "metadata": dict(record.metadata),
            "assets": [
                {
                    "asset_id": asset.asset_id,
                    "client_asset_id": asset.client_asset_id,
                    "kind": asset.kind,
                    "filename": asset.filename,
                    "media_type": asset.media_type,
                    "size_bytes": asset.size_bytes,
                    "sha256_hex": asset.sha256_hex,
                    "version": asset.version,
                    "ordinal": asset.ordinal,
                }
                for asset in record.assets
            ],
        }
        result = _record_from_json(
            await self._request_json(
                "POST",
                "/v1/records",
                operation=operation,
                json=payload,
                accepted_statuses=frozenset({200, 201}),
            ),
            operation=operation,
        )
        if (
            result.client_message_id != record.client_message_id
            or result.conversation_id != record.conversation_id
            or result.sender_user_id != record.sender_user_id
            or result.content_type != record.content_type
            or result.content != record.content
            or result.assets != record.assets
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        return result

    async def get_authorized_record(
        self,
        *,
        conversation_id: str,
        record_id: str,
        user_id: str,
    ) -> ChatRecordDTO:
        operation = "get_authorized_record"
        result = _record_from_json(
            await self._request_json(
                "GET",
                (
                    f"/v1/conversations/{quote(conversation_id, safe='')}"
                    f"/records/{quote(record_id, safe='')}"
                ),
                operation=operation,
                params={"user_id": user_id},
            ),
            operation=operation,
        )
        if (
            result.conversation_id != conversation_id
            or result.record_id != record_id
            or (
                result.sender_user_id != user_id
                and user_id not in result.recipient_user_ids
            )
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        return result

    async def list_records(self, query: ChatRecordQueryDTO) -> ChatRecordPageDTO:
        operation = "list_records"
        params: dict[str, Any] = {"user_id": query.user_id, "limit": query.limit}
        if query.cursor is not None:
            params["cursor"] = query.cursor
        data = _mapping(
            await self._request_json(
                "GET",
                f"/v1/conversations/{quote(query.conversation_id, safe='')}/records",
                operation=operation,
                params=params,
            ),
            operation=operation,
        )
        raw_records = data.get("records")
        if not isinstance(raw_records, list):
            raise ChatRecordStoreProtocolError(operation=operation)
        records = tuple(
            _record_from_json(item, operation=operation) for item in raw_records
        )
        if any(
            item.conversation_id != query.conversation_id
            or (
                item.sender_user_id != query.user_id
                and query.user_id not in item.recipient_user_ids
            )
            for item in records
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        sequences = [item.sequence for item in records]
        if sequences != sorted(set(sequences)):
            raise ChatRecordStoreProtocolError(operation=operation)
        latest_sequence = _integer(
            data,
            "latest_sequence",
            operation=operation,
        )
        if sequences and latest_sequence < sequences[-1]:
            raise ChatRecordStoreProtocolError(operation=operation)
        return ChatRecordPageDTO(
            records=records,
            next_cursor=_optional_string(data, "next_cursor", operation=operation),
            latest_sequence=latest_sequence,
        )

    async def list_user_events(
        self,
        query: ChatUserEventQueryDTO,
    ) -> ChatUserEventPageDTO:
        operation = "list_user_events"
        params: dict[str, Any] = {"limit": query.limit}
        if query.cursor is not None:
            params["cursor"] = query.cursor
        data = _mapping(
            await self._request_json(
                "GET",
                f"/v1/users/{quote(query.user_id, safe='')}/events",
                operation=operation,
                params=params,
            ),
            operation=operation,
        )
        raw_events = data.get("events")
        if not isinstance(raw_events, list):
            raise ChatRecordStoreProtocolError(operation=operation)
        events: list[ChatUserEventDTO] = []
        for raw in raw_events:
            item = _mapping(raw, operation=operation)
            event = ChatUserEventDTO(
                event_id=_required_string(item, "event_id", operation=operation),
                user_id=_required_string(item, "user_id", operation=operation),
                conversation_id=_required_string(
                    item,
                    "conversation_id",
                    operation=operation,
                ),
                record_id=_required_string(item, "record_id", operation=operation),
                record_sequence=_integer(
                    item,
                    "record_sequence",
                    operation=operation,
                    minimum=1,
                ),
                event_sequence=_integer(
                    item,
                    "event_sequence",
                    operation=operation,
                    minimum=1,
                ),
                created_at=_timestamp(item, "created_at", operation=operation),
            )
            if event.user_id != query.user_id:
                raise ChatRecordStoreProtocolError(operation=operation)
            events.append(event)
        event_sequences = [item.event_sequence for item in events]
        if event_sequences != sorted(set(event_sequences)):
            raise ChatRecordStoreProtocolError(operation=operation)
        latest_event_sequence = _integer(
            data,
            "latest_event_sequence",
            operation=operation,
        )
        if event_sequences and latest_event_sequence < event_sequences[-1]:
            raise ChatRecordStoreProtocolError(operation=operation)
        return ChatUserEventPageDTO(
            events=tuple(events),
            next_cursor=_optional_string(data, "next_cursor", operation=operation),
            latest_event_sequence=latest_event_sequence,
        )

    async def get_user_event_tail(self, user_id: str) -> ChatUserEventTailDTO:
        operation = "get_user_event_tail"
        data = _mapping(
            await self._request_json(
                "GET",
                f"/v1/users/{quote(user_id, safe='')}/events/tail",
                operation=operation,
            ),
            operation=operation,
        )
        return ChatUserEventTailDTO(
            user_id=user_id,
            cursor=_required_string(data, "cursor", operation=operation),
            latest_event_sequence=_integer(
                data,
                "latest_event_sequence",
                operation=operation,
            ),
        )

    async def _advance(
        self,
        command: ChatPositionAdvanceDTO,
        *,
        operation: str,
        suffix: str,
    ) -> ChatReceiptPositionDTO:
        result = _receipt_from_json(
            await self._request_json(
                "POST",
                f"/v1/conversations/{quote(command.conversation_id, safe='')}/{suffix}",
                operation=operation,
                json={
                    "user_id": command.user_id,
                    "through_sequence": command.through_sequence,
                    "occurred_at": _iso(command.occurred_at),
                },
            ),
            operation=operation,
        )
        if (
            result.conversation_id != command.conversation_id
            or result.user_id != command.user_id
            or result.read_through_sequence
            > result.delivered_through_sequence
            or (
                suffix == "delivery"
                and result.delivered_through_sequence < command.through_sequence
            )
            or (
                suffix == "read"
                and result.read_through_sequence < command.through_sequence
            )
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        return result

    async def advance_delivery(
        self,
        command: ChatPositionAdvanceDTO,
    ) -> ChatReceiptPositionDTO:
        return await self._advance(
            command,
            operation="advance_delivery",
            suffix="delivery",
        )

    async def advance_read(
        self,
        command: ChatPositionAdvanceDTO,
    ) -> ChatReceiptPositionDTO:
        return await self._advance(
            command,
            operation="advance_read",
            suffix="read",
        )

    async def get_unread_position(
        self,
        query: ChatPositionQueryDTO,
    ) -> ChatUnreadPositionDTO:
        operation = "get_unread_position"
        data = _mapping(
            await self._request_json(
                "GET",
                f"/v1/conversations/{quote(query.conversation_id, safe='')}/unread",
                operation=operation,
                params={"user_id": query.user_id},
            ),
            operation=operation,
        )
        result = ChatUnreadPositionDTO(
            conversation_id=_required_string(
                data,
                "conversation_id",
                operation=operation,
            ),
            user_id=_required_string(data, "user_id", operation=operation),
            unread_count=_integer(data, "unread_count", operation=operation),
            first_unread_sequence=(
                None
                if data.get("first_unread_sequence") is None
                else _integer(
                    data,
                    "first_unread_sequence",
                    operation=operation,
                    minimum=1,
                )
            ),
            latest_sequence=_integer(data, "latest_sequence", operation=operation),
        )
        if (
            result.conversation_id != query.conversation_id
            or result.user_id != query.user_id
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        return result

    async def get_unread_summary(
        self,
        query: ChatUnreadSummaryQueryDTO,
    ) -> ChatUnreadSummaryDTO:
        operation = "get_unread_summary"
        if (
            not query.user_id
            or len(query.conversation_ids) > 1000
            or len(set(query.conversation_ids)) != len(query.conversation_ids)
            or any(not conversation_id for conversation_id in query.conversation_ids)
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        data = _mapping(
            await self._request_json(
                "POST",
                f"/v1/users/{quote(query.user_id, safe='')}/unread-summary",
                operation=operation,
                json={"conversation_ids": list(query.conversation_ids)},
            ),
            operation=operation,
            exact_keys=frozenset(
                {"total_unread_count", "unread_conversation_count"}
            ),
        )
        result = ChatUnreadSummaryDTO(
            total_unread_count=_integer(
                data,
                "total_unread_count",
                operation=operation,
            ),
            unread_conversation_count=_integer(
                data,
                "unread_conversation_count",
                operation=operation,
            ),
        )
        if (
            result.unread_conversation_count > len(query.conversation_ids)
            or result.total_unread_count < result.unread_conversation_count
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        return result

    async def get_resume_position(
        self,
        query: ChatPositionQueryDTO,
    ) -> ChatResumePositionDTO:
        operation = "get_resume_position"
        data = _mapping(
            await self._request_json(
                "GET",
                f"/v1/conversations/{quote(query.conversation_id, safe='')}/resume",
                operation=operation,
                params={"user_id": query.user_id},
            ),
            operation=operation,
        )
        result = ChatResumePositionDTO(
            conversation_id=_required_string(
                data,
                "conversation_id",
                operation=operation,
            ),
            user_id=_required_string(data, "user_id", operation=operation),
            resume_cursor=_optional_string(
                data,
                "resume_cursor",
                operation=operation,
            ),
            delivered_through_sequence=_integer(
                data,
                "delivered_through_sequence",
                operation=operation,
            ),
            read_through_sequence=_integer(
                data,
                "read_through_sequence",
                operation=operation,
            ),
            latest_sequence=_integer(data, "latest_sequence", operation=operation),
        )
        if (
            result.conversation_id != query.conversation_id
            or result.user_id != query.user_id
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        return result

    async def reserve_moment(
        self,
        command: MomentDraftReserveDTO,
    ) -> MomentDraftDTO:
        operation = "reserve_moment"
        draft = _draft_from_json(
            await self._request_json(
                "POST",
                "/v1/moments/drafts",
                operation=operation,
                json={
                    "client_moment_id": command.client_moment_id,
                    "author_user_id": command.author_user_id,
                },
                accepted_statuses=frozenset({200, 201}),
            ),
            operation=operation,
        )
        if (
            draft.client_moment_id != command.client_moment_id
            or draft.author_user_id != command.author_user_id
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        return draft

    async def get_moment_draft(
        self,
        *,
        moment_id: str,
        author_user_id: str,
    ) -> MomentDraftDTO:
        operation = "get_moment_draft"
        draft = _draft_from_json(
            await self._request_json(
                "POST",
                f"/v1/moments/{quote(moment_id, safe='')}/draft/query",
                operation=operation,
                json={"author_user_id": author_user_id},
            ),
            operation=operation,
        )
        if (
            draft.moment_id != moment_id
            or draft.author_user_id != author_user_id
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        return draft

    async def publish_moment(self, command: MomentPublishDTO) -> MomentDTO:
        operation = "publish_moment"
        moment = _moment_from_json(
            await self._request_json(
                "POST",
                f"/v1/moments/{quote(command.moment_id, safe='')}/publish",
                operation=operation,
                json={
                    "author_user_id": command.author_user_id,
                    "author_org_id": command.author_org_id,
                    "content": command.content,
                    "visibility": command.visibility,
                    "audience_user_ids": list(command.audience_user_ids),
                    "audience_org_ids": list(command.audience_org_ids),
                    "assets": [
                        {
                            "asset_id": asset.asset_id,
                            "client_asset_id": asset.client_asset_id,
                            "kind": asset.kind,
                            "filename": asset.filename,
                            "media_type": asset.media_type,
                            "size_bytes": asset.size_bytes,
                            "sha256_hex": asset.sha256_hex,
                            "version": asset.version,
                            "ordinal": asset.ordinal,
                        }
                        for asset in command.assets
                    ],
                },
                accepted_statuses=frozenset({200, 201}),
            ),
            operation=operation,
        )
        if (
            moment.moment_id != command.moment_id
            or moment.client_moment_id != command.client_moment_id
            or moment.author_user_id != command.author_user_id
            or moment.author_org_id != command.author_org_id
            or moment.visibility != command.visibility
            or moment.audience_org_ids != command.audience_org_ids
            or moment.content != command.content
            or moment.assets != command.assets
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        return moment

    async def get_moment(self, query: MomentQueryDTO) -> MomentDTO:
        operation = "get_moment"
        moment = _moment_from_json(
            await self._request_json(
                "POST",
                f"/v1/moments/{quote(query.moment_id, safe='')}/query",
                operation=operation,
                json={"context": _context_json(query.context)},
            ),
            operation=operation,
        )
        if moment.moment_id != query.moment_id:
            raise ChatRecordStoreProtocolError(operation=operation)
        return moment

    async def list_moment_feed(
        self,
        query: MomentFeedQueryDTO,
    ) -> MomentFeedPageDTO:
        operation = "list_moment_feed"
        data = _mapping(
            await self._request_json(
                "POST",
                "/v1/moments/feed/query",
                operation=operation,
                json={
                    "context": _context_json(query.context),
                    "limit": query.limit,
                    "cursor": query.cursor,
                },
            ),
            operation=operation,
            exact_keys=frozenset(
                {"moments", "next_cursor", "latest_event_sequence"}
            ),
        )
        raw_moments = data.get("moments")
        if not isinstance(raw_moments, list) or len(raw_moments) > query.limit:
            raise ChatRecordStoreProtocolError(operation=operation)
        return MomentFeedPageDTO(
            moments=tuple(
                _moment_from_json(item, operation=operation)
                for item in raw_moments
            ),
            next_cursor=_optional_string(
                data,
                "next_cursor",
                operation=operation,
            ),
            latest_event_sequence=_integer(
                data,
                "latest_event_sequence",
                operation=operation,
            ),
        )

    async def set_moment_like(
        self,
        command: MomentLikeCommandDTO,
    ) -> MomentLikeResultDTO:
        operation = "set_moment_like"
        suffix = "likes" if command.liked else "likes/remove"
        result = _like_result_from_json(
            await self._request_json(
                "POST",
                f"/v1/moments/{quote(command.moment_id, safe='')}/{suffix}",
                operation=operation,
                json={
                    "context": _context_json(command.context),
                    "user_id": command.context.viewer_user_id,
                    "occurred_at": _iso(command.occurred_at),
                },
            ),
            operation=operation,
        )
        if (
            result.moment_id != command.moment_id
            or result.user_id != command.context.viewer_user_id
            or result.liked != command.liked
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        return result

    async def list_moment_likes(
        self,
        query: MomentLikeQueryDTO,
    ) -> MomentLikePageDTO:
        operation = "list_moment_likes"
        data = _mapping(
            await self._request_json(
                "POST",
                f"/v1/moments/{quote(query.moment_id, safe='')}/likes/query",
                operation=operation,
                json={
                    "context": _context_json(query.context),
                    "limit": query.limit,
                    "cursor": query.cursor,
                },
            ),
            operation=operation,
            exact_keys=frozenset({"items", "count", "next_cursor"}),
        )
        raw_items = data.get("items")
        count = _integer(data, "count", operation=operation)
        if (
            not isinstance(raw_items, list)
            or len(raw_items) > query.limit
            or count < len(raw_items)
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        likes: list[MomentLikeDTO] = []
        for raw in raw_items:
            item = _mapping(
                raw,
                operation=operation,
                exact_keys=frozenset({"user_id", "sequence", "liked_at"}),
            )
            likes.append(
                MomentLikeDTO(
                    user_id=_required_string(
                        item,
                        "user_id",
                        operation=operation,
                    ),
                    sequence=_integer(
                        item,
                        "sequence",
                        operation=operation,
                        minimum=1,
                    ),
                    created_at=_timestamp(
                        item,
                        "liked_at",
                        operation=operation,
                    ),
                )
            )
        return MomentLikePageDTO(
            likes=tuple(likes),
            next_cursor=_optional_string(
                data,
                "next_cursor",
                operation=operation,
            ),
        )

    async def create_moment_comment(
        self,
        command: MomentCommentCreateDTO,
    ) -> MomentCommentDTO:
        operation = "create_moment_comment"
        comment = _comment_from_json(
            await self._request_json(
                "POST",
                f"/v1/moments/{quote(command.moment_id, safe='')}/comments",
                operation=operation,
                json={
                    "context": _context_json(command.context),
                    "client_comment_id": command.client_comment_id,
                    "author_user_id": command.author_user_id,
                    "content": command.content,
                },
                accepted_statuses=frozenset({200, 201}),
            ),
            operation=operation,
        )
        if (
            comment.moment_id != command.moment_id
            or comment.author_user_id != command.author_user_id
            or comment.client_comment_id != command.client_comment_id
            or comment.content != command.content
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        return comment

    async def list_moment_comments(
        self,
        query: MomentCommentQueryDTO,
    ) -> MomentCommentPageDTO:
        operation = "list_moment_comments"
        data = _mapping(
            await self._request_json(
                "POST",
                f"/v1/moments/{quote(query.moment_id, safe='')}/comments/query",
                operation=operation,
                json={
                    "context": _context_json(query.context),
                    "limit": query.limit,
                    "cursor": query.cursor,
                },
            ),
            operation=operation,
            exact_keys=frozenset({"items", "count", "next_cursor"}),
        )
        raw_items = data.get("items")
        count = _integer(data, "count", operation=operation)
        if (
            not isinstance(raw_items, list)
            or len(raw_items) > query.limit
            or count < len(raw_items)
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        comments = tuple(
            _comment_from_json(item, operation=operation)
            for item in raw_items
        )
        if any(comment.moment_id != query.moment_id for comment in comments):
            raise ChatRecordStoreProtocolError(operation=operation)
        return MomentCommentPageDTO(
            comments=comments,
            next_cursor=_optional_string(
                data,
                "next_cursor",
                operation=operation,
            ),
        )

    async def delete_moment_comment(
        self,
        command: MomentCommentDeleteDTO,
    ) -> MomentCommentDeleteResultDTO:
        operation = "delete_moment_comment"
        data = _mapping(
            await self._request_json(
                "POST",
                (
                    f"/v1/moments/{quote(command.moment_id, safe='')}"
                    f"/comments/{quote(command.comment_id, safe='')}/delete"
                ),
                operation=operation,
                json={
                    "context": _context_json(command.context),
                    "requested_by_user_id": command.requested_by_user_id,
                    "requested_at": _iso(command.requested_at),
                },
            ),
            operation=operation,
            exact_keys=frozenset(
                {
                    "moment_id",
                    "comment_id",
                    "changed",
                    "comment_count",
                    "deleted_at",
                }
            ),
        )
        moment_id = _required_string(data, "moment_id", operation=operation)
        comment_id = _required_string(data, "comment_id", operation=operation)
        if (
            moment_id != command.moment_id
            or comment_id != command.comment_id
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        return MomentCommentDeleteResultDTO(
            moment_id=moment_id,
            comment_id=comment_id,
            state="deleted",
            changed=_boolean(data, "changed", operation=operation),
            comment_count=_integer(
                data,
                "comment_count",
                operation=operation,
            ),
            deleted_at=_timestamp(data, "deleted_at", operation=operation),
        )

    async def begin_moment_delete(
        self,
        command: MomentDeleteCommandDTO,
    ) -> MomentDeleteResultDTO:
        operation = "begin_moment_delete"
        result = _delete_result_from_json(
            await self._request_json(
                "POST",
                f"/v1/moments/{quote(command.moment_id, safe='')}/delete",
                operation=operation,
                json={
                    "context": _context_json(command.context),
                    "requested_by_user_id": command.requested_by_user_id,
                    "requested_at": _iso(command.requested_at),
                },
            ),
            operation=operation,
        )
        if result.moment_id != command.moment_id:
            raise ChatRecordStoreProtocolError(operation=operation)
        return result

    async def complete_moment_delete(
        self,
        command: MomentDeleteCommandDTO,
    ) -> MomentDeleteResultDTO:
        operation = "complete_moment_delete"
        result = _delete_result_from_json(
            await self._request_json(
                "POST",
                (
                    f"/v1/moments/{quote(command.moment_id, safe='')}"
                    "/delete/complete"
                ),
                operation=operation,
                json={
                    "requested_by_user_id": command.requested_by_user_id,
                    "completed_at": _iso(command.requested_at),
                },
            ),
            operation=operation,
        )
        if result.moment_id != command.moment_id or result.state != "deleted":
            raise ChatRecordStoreProtocolError(operation=operation)
        return result

    async def list_moment_events(
        self,
        query: MomentUserEventQueryDTO,
    ) -> MomentUserEventPageDTO:
        operation = "list_moment_events"
        data = _mapping(
            await self._request_json(
                "POST",
                "/v1/moments/events/query",
                operation=operation,
                json={
                    "context": _context_json(query.context),
                    "limit": query.limit,
                    "cursor": query.cursor,
                },
            ),
            operation=operation,
            exact_keys=frozenset(
                {"events", "next_cursor", "latest_event_sequence"}
            ),
        )
        raw_events = data.get("events")
        if not isinstance(raw_events, list) or len(raw_events) > query.limit:
            raise ChatRecordStoreProtocolError(operation=operation)
        events = tuple(
            _moment_event_from_json(
                item,
                operation=operation,
                user_id=query.context.viewer_user_id,
            )
            for item in raw_events
        )
        if any(event.user_id != query.context.viewer_user_id for event in events):
            raise ChatRecordStoreProtocolError(operation=operation)
        return MomentUserEventPageDTO(
            events=events,
            next_cursor=_optional_string(
                data,
                "next_cursor",
                operation=operation,
            ),
            latest_event_sequence=_integer(
                data,
                "latest_event_sequence",
                operation=operation,
            ),
        )

    async def get_moment_event_tail(
        self,
        context: MomentViewerContextDTO,
    ) -> MomentUserEventTailDTO:
        operation = "get_moment_event_tail"
        data = _mapping(
            await self._request_json(
                "POST",
                "/v1/moments/events/tail",
                operation=operation,
                json={"context": _context_json(context)},
            ),
            operation=operation,
            exact_keys=frozenset(
                {"cursor", "latest_event_sequence"}
            ),
        )
        return MomentUserEventTailDTO(
            user_id=context.viewer_user_id,
            cursor=_required_string(data, "cursor", operation=operation),
            latest_event_sequence=_integer(
                data,
                "latest_event_sequence",
                operation=operation,
            ),
        )

    async def delete_records(
        self,
        command: ChatRecordDeleteCommandDTO,
    ) -> ChatRecordMutationResultDTO:
        operation = "delete_records"
        return self._mutation_result(
            await self._request_json(
                "POST",
                "/v1/records/delete",
                operation=operation,
                json={
                    "conversation_id": command.conversation_id,
                    "record_ids": list(command.record_ids),
                    "requested_by_user_id": command.requested_by_user_id,
                    "reason": command.reason,
                    "requested_at": _iso(command.requested_at),
                },
            ),
            operation=operation,
        )

    async def apply_retention_batch(
        self,
        command: ChatRetentionBatchCommandDTO,
    ) -> ChatRetentionBatchResultDTO:
        operation = "apply_retention_batch"
        data = _mapping(
            await self._request_json(
                "POST",
                "/v1/retention/apply",
                operation=operation,
                json={
                    "operation_id": command.operation_id,
                    "batch_ordinal": command.batch_ordinal,
                    "approved_maximum_records": command.approved_maximum_records,
                    "approved_maximum_asset_jobs": command.approved_maximum_asset_jobs,
                    "requested_by_user_id": command.requested_by_user_id,
                    "reason": command.reason,
                    "requested_at": _iso(command.requested_at),
                    "delete_before": _iso(command.delete_before),
                    "conversation_id": command.conversation_id,
                    "maximum_records": command.maximum_records,
                },
            ),
            operation=operation,
            exact_keys=frozenset(
                {
                    "operation_id",
                    "batch_ordinal",
                    "affected_count",
                    "cumulative_affected_count",
                    "operation_complete",
                    "completed_at",
                }
            ),
        )
        operation_id = _required_string(data, "operation_id", operation=operation)
        batch_ordinal = _integer(data, "batch_ordinal", operation=operation)
        affected_count = _integer(data, "affected_count", operation=operation)
        cumulative_affected_count = _integer(
            data,
            "cumulative_affected_count",
            operation=operation,
        )
        if (
            operation_id != command.operation_id
            or batch_ordinal != command.batch_ordinal
            or affected_count > command.maximum_records
            or cumulative_affected_count < affected_count
            or cumulative_affected_count > command.approved_maximum_records
        ):
            raise ChatRecordStoreProtocolError(operation=operation)
        return ChatRetentionBatchResultDTO(
            operation_id=operation_id,
            batch_ordinal=batch_ordinal,
            affected_count=affected_count,
            cumulative_affected_count=cumulative_affected_count,
            operation_complete=_boolean(
                data,
                "operation_complete",
                operation=operation,
            ),
            completed_at=_timestamp(data, "completed_at", operation=operation),
        )

    @staticmethod
    def _mutation_result(
        raw: Any,
        *,
        operation: str,
    ) -> ChatRecordMutationResultDTO:
        data = _mapping(raw, operation=operation)
        return ChatRecordMutationResultDTO(
            affected_count=_integer(data, "affected_count", operation=operation),
            completed_at=_timestamp(data, "completed_at", operation=operation),
        )


def configured_chat_record_capability() -> StorageCapabilityDescription:
    """Return configured capability metadata without opening a connection."""

    return StorageCapabilityDescription(
        store_name="chat_record_store",
        status="configured",
        configured=True,
        readable=True,
        writable=True,
        durable=True,
        external_io_enabled=True,
        operations=tuple(
            dict.fromkeys(CHAT_RECORD_STORE_OPERATIONS + MOMENT_STORE_OPERATIONS)
        ),
        reason="C19 record service is configured for chat and Moments.",
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_TIMEOUT_SECONDS",
    "RECORD_STORE_TIMEOUT_ENV",
    "RECORD_STORE_TOKEN_ENV",
    "RECORD_STORE_URL_ENV",
    "ChatRecordStoreAuthenticationError",
    "ChatRecordStoreConflictError",
    "ChatRecordStoreHttpError",
    "ChatRecordStoreProtocolError",
    "ChatRecordStoreRejectedError",
    "ChatRecordStoreUnavailableError",
    "HttpChatRecordStore",
    "HttpChatRecordStoreConfig",
    "configured_chat_record_capability",
]
