"""Strict HTTP adapter for the independently deployable C19 asset service.

Only authenticated JSON metadata crosses this boundary. File bytes, physical
object keys and durable provider URLs are deliberately absent.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from ipaddress import ip_address
from typing import Any, Mapping, NoReturn
from urllib.parse import quote, urlsplit

import httpx

from .storage import (
    CHAT_ASSET_STORE_OPERATIONS,
    ChatAssetBindingCommitCommandDTO,
    ChatAssetBindingPrepareCommandDTO,
    ChatAssetBindingResultDTO,
    ChatAssetDTO,
    ChatAssetDeleteCommandDTO,
    ChatAssetDownloadIntentDTO,
    ChatAssetDownloadRequestDTO,
    ChatAssetFinalizeCommandDTO,
    ChatAssetLookupDTO,
    ChatAssetLifecycleResultDTO,
    ChatAssetQuarantineCommandDTO,
    ChatAssetTransferInspectDTO,
    ChatAssetTransferInspectionDTO,
    ChatAssetUploadHandleDTO,
    ChatAssetUploadMetadataDTO,
    StorageCapabilityDescription,
)
from .moment_storage import (
    MOMENT_ASSET_STORE_OPERATIONS,
    MomentAssetBindingCommitDTO,
    MomentAssetBindingPrepareDTO,
    MomentAssetBindingResultDTO,
    MomentAssetDTO,
    MomentAssetDownloadRequestDTO,
    MomentAssetFinalizeDTO,
    MomentAssetLookupDTO,
    MomentAssetUploadHandleDTO,
    MomentAssetUploadMetadataDTO,
    ScopedAssetTransferInspectionDTO,
)


ASSET_STORE_URL_ENV = "C19_ASSET_STORE_URL"
ASSET_STORE_TOKEN_ENV = "C19_ASSET_STORE_TOKEN"
ASSET_STORE_TIMEOUT_ENV = "C19_ASSET_STORE_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_TIMEOUT_SECONDS = 60.0
MAX_ASSET_BYTES = 64 * 1024 * 1024

_ASSET_ID_RE = re.compile(r"^att_[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TICKET_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_MOMENT_ID_RE = re.compile(r"^mom_[0-9a-f]{32}$")
_ASSET_STATUSES = frozenset(
    {
        "pending_upload",
        "uploaded",
        "scanning",
        "active",
        "rejected",
        "quarantined",
        "delete_pending",
        "deleted",
        "expired",
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


class ChatAssetStoreHttpError(RuntimeError):
    """Stable content-free failure raised by the asset HTTP boundary."""

    code = "c19_asset_store_error"
    retryable = False

    def __init__(self, *, operation: str, status_code: int | None = None) -> None:
        self.operation = operation
        self.status_code = status_code
        super().__init__(f"C19 asset store operation failed: {self.code}.")


class ChatAssetStoreUnavailableError(ChatAssetStoreHttpError):
    code = "c19_asset_store_unavailable"
    retryable = True


class ChatAssetStoreAuthenticationError(ChatAssetStoreHttpError):
    code = "c19_asset_store_authentication_failed"


class ChatAssetStoreConflictError(ChatAssetStoreHttpError):
    code = "c19_asset_store_conflict"


class ChatAssetStoreRejectedError(ChatAssetStoreHttpError):
    code = "c19_asset_store_request_rejected"


class ChatAssetStoreQuotaError(ChatAssetStoreHttpError):
    code = "c19_asset_store_quota_exceeded"


class ChatAssetStoreProtocolError(ChatAssetStoreHttpError):
    code = "c19_asset_store_invalid_response"


def _is_private_http_hostname(hostname: str) -> bool:
    lowered = hostname.lower().rstrip(".")
    try:
        address = ip_address(lowered)
    except ValueError:
        return (
            "." not in lowered
            or lowered == "localhost"
            or lowered.endswith(
                (".localhost", ".internal", ".local", ".svc", ".svc.cluster.local")
            )
        )
    return address.is_private or address.is_loopback or address.is_link_local


@dataclass(frozen=True, slots=True)
class HttpChatAssetStoreConfig:
    """Validated adapter configuration with a redacted token representation."""

    base_url: str
    token: str = field(repr=False)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        normalized = self.base_url.strip().rstrip("/")
        parsed = urlsplit(normalized)
        try:
            port = parsed.port
        except ValueError:
            raise ValueError("C19 asset store URL is invalid.") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or (port is not None and not 1 <= port <= 65_535)
        ):
            raise ValueError("C19 asset store URL is invalid.")
        if parsed.scheme == "http" and not _is_private_http_hostname(
            parsed.hostname
        ):
            raise ValueError("C19 asset store HTTP is allowed only on a private host.")
        if len(self.token) < 32 or self.token != self.token.strip():
            raise ValueError("C19 asset store token is invalid.")
        if not (0 < float(self.timeout_seconds) <= MAX_TIMEOUT_SECONDS):
            raise ValueError("C19 asset store timeout is invalid.")
        object.__setattr__(self, "base_url", normalized)
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> HttpChatAssetStoreConfig | None:
        values = os.environ if environ is None else environ
        base_url = values.get(ASSET_STORE_URL_ENV, "").strip()
        token = values.get(ASSET_STORE_TOKEN_ENV, "")
        if not base_url or not token:
            return None
        timeout_raw = values.get(ASSET_STORE_TIMEOUT_ENV, "").strip()
        timeout = DEFAULT_TIMEOUT_SECONDS if not timeout_raw else float(timeout_raw)
        return cls(base_url=base_url, token=token, timeout_seconds=timeout)


def _mapping(
    value: Any,
    *,
    operation: str,
    exact_keys: frozenset[str] | None = None,
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ChatAssetStoreProtocolError(operation=operation)
    if exact_keys is not None and frozenset(value) != exact_keys:
        raise ChatAssetStoreProtocolError(operation=operation)
    return value


def _string(data: Mapping[str, Any], key: str, *, operation: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ChatAssetStoreProtocolError(operation=operation)
    return value


def _integer(
    data: Mapping[str, Any],
    key: str,
    *,
    operation: str,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    value = data.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise ChatAssetStoreProtocolError(operation=operation)
    return value


def _timestamp(data: Mapping[str, Any], key: str, *, operation: str) -> datetime:
    raw = _string(data, key, operation=operation)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ChatAssetStoreProtocolError(operation=operation) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ChatAssetStoreProtocolError(operation=operation)
    return parsed


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("C19 asset timestamps must be timezone-aware.")
    return value.isoformat()


_ASSET_KEYS = frozenset(
    {
        "asset_id",
        "client_asset_id",
        "owner_user_id",
        "conversation_id",
        "kind",
        "filename",
        "media_type",
        "size_bytes",
        "sha256_hex",
        "version",
        "status",
    }
)


def _asset_from_json(value: Any, *, operation: str) -> ChatAssetDTO:
    data = _mapping(value, operation=operation, exact_keys=_ASSET_KEYS)
    asset_id = _string(data, "asset_id", operation=operation)
    client_asset_id = _string(data, "client_asset_id", operation=operation)
    owner_user_id = _string(data, "owner_user_id", operation=operation)
    conversation_id = _string(data, "conversation_id", operation=operation)
    kind = _string(data, "kind", operation=operation)
    filename = _string(data, "filename", operation=operation)
    media_type = _string(data, "media_type", operation=operation)
    sha256_hex = _string(data, "sha256_hex", operation=operation)
    status = _string(data, "status", operation=operation)
    if (
        _ASSET_ID_RE.fullmatch(asset_id) is None
        or len(client_asset_id) > 128
        or len(owner_user_id) > 64
        or len(conversation_id) > 64
        or any(
            ord(character) < 32 or ord(character) == 127
            for value in (client_asset_id, owner_user_id, conversation_id)
            for character in value
        )
        or kind not in {"image", "file"}
        or len(filename) > 255
        or unicodedata.normalize("NFC", filename) != filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or any(
            unicodedata.category(character).startswith("C")
            for character in filename
        )
        or _SHA256_RE.fullmatch(sha256_hex) is None
        or status not in _ASSET_STATUSES
        or media_type != media_type.lower()
        or ";" in media_type
        or (kind == "image" and media_type not in _IMAGE_MEDIA_TYPES)
        or (kind == "file" and media_type not in _FILE_MEDIA_TYPES)
    ):
        raise ChatAssetStoreProtocolError(operation=operation)
    return ChatAssetDTO(
        asset_id=asset_id,
        client_asset_id=client_asset_id,
        owner_user_id=owner_user_id,
        conversation_id=conversation_id,
        kind=kind,  # type: ignore[arg-type]
        filename=filename,
        media_type=media_type,
        size_bytes=_integer(
            data,
            "size_bytes",
            operation=operation,
            minimum=1,
            maximum=MAX_ASSET_BYTES,
        ),
        sha256_hex=sha256_hex,
        version=_integer(data, "version", operation=operation, minimum=1),
        status=status,  # type: ignore[arg-type]
    )


def _assert_asset_scope(
    asset: ChatAssetDTO,
    *,
    operation: str,
    asset_id: str | None = None,
    owner_user_id: str,
    conversation_id: str,
) -> None:
    if (
        (asset_id is not None and asset.asset_id != asset_id)
        or asset.owner_user_id != owner_user_id
        or asset.conversation_id != conversation_id
    ):
        raise ChatAssetStoreProtocolError(operation=operation)


_MOMENT_ASSET_KEYS = frozenset(
    {
        "asset_id",
        "client_asset_id",
        "owner_user_id",
        "usage",
        "scope_id",
        "kind",
        "filename",
        "media_type",
        "size_bytes",
        "sha256_hex",
        "version",
        "status",
    }
)


def _moment_asset_from_json(value: Any, *, operation: str) -> MomentAssetDTO:
    data = _mapping(value, operation=operation, exact_keys=_MOMENT_ASSET_KEYS)
    asset_id = _string(data, "asset_id", operation=operation)
    client_asset_id = _string(data, "client_asset_id", operation=operation)
    owner_user_id = _string(data, "owner_user_id", operation=operation)
    usage = _string(data, "usage", operation=operation)
    scope_id = _string(data, "scope_id", operation=operation)
    kind = _string(data, "kind", operation=operation)
    filename = _string(data, "filename", operation=operation)
    media_type = _string(data, "media_type", operation=operation)
    sha256_hex = _string(data, "sha256_hex", operation=operation)
    status = _string(data, "status", operation=operation)
    if (
        _ASSET_ID_RE.fullmatch(asset_id) is None
        or not 1 <= len(client_asset_id) <= 128
        or not 1 <= len(owner_user_id) <= 128
        or usage != "moment_image"
        or _MOMENT_ID_RE.fullmatch(scope_id) is None
        or kind != "image"
        or len(filename) > 255
        or unicodedata.normalize("NFC", filename) != filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or any(
            unicodedata.category(character).startswith("C")
            for character in filename
        )
        or media_type not in _IMAGE_MEDIA_TYPES
        or _SHA256_RE.fullmatch(sha256_hex) is None
        or status not in _ASSET_STATUSES
    ):
        raise ChatAssetStoreProtocolError(operation=operation)
    return MomentAssetDTO(
        asset_id=asset_id,
        client_asset_id=client_asset_id,
        owner_user_id=owner_user_id,
        moment_id=scope_id,
        kind="image",
        filename=filename,
        media_type=media_type,
        size_bytes=_integer(
            data,
            "size_bytes",
            operation=operation,
            minimum=1,
            maximum=MAX_ASSET_BYTES,
        ),
        sha256_hex=sha256_hex,
        version=_integer(data, "version", operation=operation, minimum=1),
        status=status,  # type: ignore[arg-type]
    )


def _assert_moment_asset_scope(
    asset: MomentAssetDTO,
    *,
    operation: str,
    asset_id: str | None = None,
    owner_user_id: str,
    moment_id: str,
) -> None:
    if (
        (asset_id is not None and asset.asset_id != asset_id)
        or asset.owner_user_id != owner_user_id
        or asset.moment_id != moment_id
    ):
        raise ChatAssetStoreProtocolError(operation=operation)


class HttpChatAssetStore:
    """HTTP implementation of the metadata-only ``ChatAssetStore`` boundary."""

    def __init__(
        self,
        config: HttpChatAssetStoreConfig,
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
        return configured_chat_asset_capability()

    async def __aenter__(self) -> HttpChatAssetStore:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        accepted_statuses: frozenset[int] = frozenset({200}),
        expect_body: bool = True,
    ) -> Any:
        try:
            response = await self._client.request(
                method,
                path.lstrip("/"),
                headers={
                    "Authorization": f"Bearer {self._config.token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                params=params,
                json=json,
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RequestError):
            raise ChatAssetStoreUnavailableError(operation=operation) from None
        if response.status_code not in accepted_statuses:
            self._raise_response_error(operation=operation, status_code=response.status_code)
        if not expect_body:
            if response.content not in {b"", b"null"}:
                raise ChatAssetStoreProtocolError(operation=operation)
            return None
        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        if (
            content_type.strip().lower() != "application/json"
            or len(response.content) > 262_144
        ):
            raise ChatAssetStoreProtocolError(operation=operation)
        try:
            return response.json()
        except ValueError:
            raise ChatAssetStoreProtocolError(operation=operation) from None

    @staticmethod
    def _raise_response_error(*, operation: str, status_code: int) -> NoReturn:
        if status_code in {401, 403}:
            raise ChatAssetStoreAuthenticationError(
                operation=operation, status_code=status_code
            )
        if status_code == 409:
            raise ChatAssetStoreConflictError(
                operation=operation, status_code=status_code
            )
        if status_code in {400, 404, 410, 413, 415, 422}:
            raise ChatAssetStoreRejectedError(
                operation=operation, status_code=status_code
            )
        if status_code == 429:
            raise ChatAssetStoreQuotaError(
                operation=operation, status_code=status_code
            )
        if status_code >= 500:
            raise ChatAssetStoreUnavailableError(
                operation=operation, status_code=status_code
            )
        raise ChatAssetStoreProtocolError(operation=operation, status_code=status_code)

    async def create_upload_intent(
        self,
        metadata: ChatAssetUploadMetadataDTO,
    ) -> ChatAssetUploadHandleDTO:
        operation = "create_upload_intent"
        data = _mapping(
            await self._request_json(
                "POST",
                "/v1/upload-intents",
                operation=operation,
                json={
                    "client_asset_id": metadata.client_asset_id,
                    "owner_user_id": metadata.owner_user_id,
                    "conversation_id": metadata.conversation_id,
                    "kind": metadata.kind,
                    "filename": metadata.filename,
                    "media_type": metadata.media_type,
                    "size_bytes": metadata.size_bytes,
                    "sha256_hex": metadata.sha256_hex,
                    "requested_at": _iso(metadata.requested_at),
                },
                accepted_statuses=frozenset({200, 201}),
            ),
            operation=operation,
            exact_keys=frozenset({"asset", "upload_ticket", "expires_at"}),
        )
        asset = _asset_from_json(data["asset"], operation=operation)
        _assert_asset_scope(
            asset,
            operation=operation,
            owner_user_id=metadata.owner_user_id,
            conversation_id=metadata.conversation_id,
        )
        ticket = data.get("upload_ticket")
        expires_at = data.get("expires_at")
        if (ticket is None) != (expires_at is None):
            raise ChatAssetStoreProtocolError(operation=operation)
        parsed_expiry: datetime | None = None
        if ticket is not None:
            if not isinstance(ticket, str) or _TICKET_RE.fullmatch(ticket) is None:
                raise ChatAssetStoreProtocolError(operation=operation)
            parsed_expiry = _timestamp(data, "expires_at", operation=operation)
        return ChatAssetUploadHandleDTO(
            asset=asset,
            opaque_ticket=ticket,
            expires_at=parsed_expiry,
        )

    async def get_asset(self, query: ChatAssetLookupDTO) -> ChatAssetDTO:
        operation = "get_asset"
        asset = _asset_from_json(
            await self._request_json(
                "GET",
                f"/v1/assets/{quote(query.asset_id, safe='')}",
                operation=operation,
                params={
                    "owner_user_id": query.owner_user_id,
                    "conversation_id": query.conversation_id,
                },
            ),
            operation=operation,
        )
        _assert_asset_scope(
            asset,
            operation=operation,
            asset_id=query.asset_id,
            owner_user_id=query.owner_user_id,
            conversation_id=query.conversation_id,
        )
        return asset

    async def finalize_upload(
        self,
        command: ChatAssetFinalizeCommandDTO,
    ) -> ChatAssetDTO:
        operation = "finalize_upload"
        asset = _asset_from_json(
            await self._request_json(
                "POST",
                f"/v1/assets/{quote(command.asset_id, safe='')}/finalize",
                operation=operation,
                json={
                    "owner_user_id": command.owner_user_id,
                    "conversation_id": command.conversation_id,
                },
            ),
            operation=operation,
        )
        _assert_asset_scope(
            asset,
            operation=operation,
            asset_id=command.asset_id,
            owner_user_id=command.owner_user_id,
            conversation_id=command.conversation_id,
        )
        return asset

    async def _binding(
        self,
        command: ChatAssetBindingPrepareCommandDTO | ChatAssetBindingCommitCommandDTO,
        *,
        operation: str,
        suffix: str,
    ) -> ChatAssetBindingResultDTO:
        payload: dict[str, Any] = {
            "owner_user_id": command.owner_user_id,
            "conversation_id": command.conversation_id,
            "client_message_id": command.client_message_id,
        }
        if isinstance(command, ChatAssetBindingCommitCommandDTO):
            payload["record_id"] = command.record_id
        data = _mapping(
            await self._request_json(
                "POST",
                f"/v1/assets/{quote(command.asset_id, safe='')}/bindings/{suffix}",
                operation=operation,
                json=payload,
            ),
            operation=operation,
            exact_keys=frozenset({"asset", "binding_status"}),
        )
        asset = _asset_from_json(data["asset"], operation=operation)
        _assert_asset_scope(
            asset,
            operation=operation,
            asset_id=command.asset_id,
            owner_user_id=command.owner_user_id,
            conversation_id=command.conversation_id,
        )
        binding_status = _string(data, "binding_status", operation=operation)
        allowed = {"committed"} if suffix == "commit" else {"prepared", "committed"}
        if binding_status not in allowed or asset.status != "active":
            raise ChatAssetStoreProtocolError(operation=operation)
        return ChatAssetBindingResultDTO(
            asset=asset,
            binding_status=binding_status,  # type: ignore[arg-type]
        )

    async def prepare_binding(
        self,
        command: ChatAssetBindingPrepareCommandDTO,
    ) -> ChatAssetBindingResultDTO:
        return await self._binding(command, operation="prepare_binding", suffix="prepare")

    async def commit_binding(
        self,
        command: ChatAssetBindingCommitCommandDTO,
    ) -> ChatAssetBindingResultDTO:
        return await self._binding(command, operation="commit_binding", suffix="commit")

    async def create_download_intent(
        self,
        command: ChatAssetDownloadRequestDTO,
    ) -> ChatAssetDownloadIntentDTO:
        operation = "create_download_intent"
        data = _mapping(
            await self._request_json(
                "POST",
                f"/v1/assets/{quote(command.asset_id, safe='')}/download-intents",
                operation=operation,
                json={
                    "owner_user_id": command.owner_user_id,
                    "reader_user_id": command.reader_user_id,
                    "conversation_id": command.conversation_id,
                    "record_id": command.record_id,
                    "variant": command.variant,
                    "disposition": command.disposition,
                    "asset_version": command.asset_version,
                },
                accepted_statuses=frozenset({200, 201}),
            ),
            operation=operation,
            exact_keys=frozenset({"download_ticket", "expires_at"}),
        )
        ticket = _string(data, "download_ticket", operation=operation)
        if _TICKET_RE.fullmatch(ticket) is None:
            raise ChatAssetStoreProtocolError(operation=operation)
        return ChatAssetDownloadIntentDTO(
            opaque_ticket=ticket,
            expires_at=_timestamp(data, "expires_at", operation=operation),
        )

    async def inspect_transfer(
        self,
        command: ChatAssetTransferInspectDTO,
    ) -> ChatAssetTransferInspectionDTO:
        operation = "inspect_transfer"
        data = _mapping(
            await self._request_json(
                "POST",
                "/v1/transfers/inspect",
                operation=operation,
                json={
                    "ticket": command.opaque_ticket,
                    "direction": command.direction,
                    "method": command.method,
                },
            ),
            operation=operation,
            exact_keys=frozenset(
                {
                    "asset_id",
                    "owner_user_id",
                    "reader_user_id",
                    "conversation_id",
                    "record_id",
                    "variant",
                    "version",
                    "expires_at",
                }
            ),
        )
        asset_id = _string(data, "asset_id", operation=operation)
        owner_user_id = _string(data, "owner_user_id", operation=operation)
        conversation_id = _string(data, "conversation_id", operation=operation)
        reader_user_id = data.get("reader_user_id")
        record_id = data.get("record_id")
        variant = data.get("variant")
        if _ASSET_ID_RE.fullmatch(asset_id) is None:
            raise ChatAssetStoreProtocolError(operation=operation)
        if command.direction == "upload":
            if (
                command.method != "PUT"
                or reader_user_id is not None
                or record_id is not None
                or variant is not None
            ):
                raise ChatAssetStoreProtocolError(operation=operation)
        elif (
            command.method not in {"GET", "HEAD"}
            or not isinstance(reader_user_id, str)
            or not reader_user_id
            or not isinstance(record_id, str)
            or not record_id
            or variant not in {"original", "thumbnail"}
        ):
            raise ChatAssetStoreProtocolError(operation=operation)
        return ChatAssetTransferInspectionDTO(
            asset_id=asset_id,
            owner_user_id=owner_user_id,
            reader_user_id=reader_user_id,
            conversation_id=conversation_id,
            record_id=record_id,
            variant=variant,  # type: ignore[arg-type]
            version=_integer(data, "version", operation=operation, minimum=1),
            expires_at=_timestamp(data, "expires_at", operation=operation),
        )

    async def create_moment_upload_intent(
        self,
        metadata: MomentAssetUploadMetadataDTO,
    ) -> MomentAssetUploadHandleDTO:
        operation = "create_moment_upload_intent"
        data = _mapping(
            await self._request_json(
                "POST",
                "/v1/moment-assets/upload-intents",
                operation=operation,
                json={
                    "client_asset_id": metadata.client_asset_id,
                    "owner_user_id": metadata.owner_user_id,
                    "scope_id": metadata.moment_id,
                    "kind": "image",
                    "filename": metadata.filename,
                    "media_type": metadata.media_type,
                    "size_bytes": metadata.size_bytes,
                    "sha256_hex": metadata.sha256_hex,
                    "requested_at": _iso(metadata.requested_at),
                },
                accepted_statuses=frozenset({200, 201}),
            ),
            operation=operation,
            exact_keys=frozenset({"asset", "upload_ticket", "expires_at"}),
        )
        asset = _moment_asset_from_json(data["asset"], operation=operation)
        _assert_moment_asset_scope(
            asset,
            operation=operation,
            owner_user_id=metadata.owner_user_id,
            moment_id=metadata.moment_id,
        )
        ticket = data.get("upload_ticket")
        expires_at = data.get("expires_at")
        if (ticket is None) != (expires_at is None):
            raise ChatAssetStoreProtocolError(operation=operation)
        parsed_expiry: datetime | None = None
        if ticket is not None:
            if not isinstance(ticket, str) or _TICKET_RE.fullmatch(ticket) is None:
                raise ChatAssetStoreProtocolError(operation=operation)
            parsed_expiry = _timestamp(data, "expires_at", operation=operation)
        return MomentAssetUploadHandleDTO(
            asset=asset,
            opaque_ticket=ticket,
            expires_at=parsed_expiry,
        )

    async def get_moment_asset(
        self,
        query: MomentAssetLookupDTO,
    ) -> MomentAssetDTO:
        operation = "get_moment_asset"
        asset = _moment_asset_from_json(
            await self._request_json(
                "GET",
                f"/v1/moment-assets/{quote(query.asset_id, safe='')}",
                operation=operation,
                params={
                    "owner_user_id": query.owner_user_id,
                    "scope_id": query.moment_id,
                },
            ),
            operation=operation,
        )
        _assert_moment_asset_scope(
            asset,
            operation=operation,
            asset_id=query.asset_id,
            owner_user_id=query.owner_user_id,
            moment_id=query.moment_id,
        )
        return asset

    async def finalize_moment_upload(
        self,
        command: MomentAssetFinalizeDTO,
    ) -> MomentAssetDTO:
        operation = "finalize_moment_upload"
        asset = _moment_asset_from_json(
            await self._request_json(
                "POST",
                f"/v1/moment-assets/{quote(command.asset_id, safe='')}/finalize",
                operation=operation,
                json={
                    "owner_user_id": command.owner_user_id,
                    "scope_id": command.moment_id,
                },
            ),
            operation=operation,
        )
        _assert_moment_asset_scope(
            asset,
            operation=operation,
            asset_id=command.asset_id,
            owner_user_id=command.owner_user_id,
            moment_id=command.moment_id,
        )
        return asset

    async def _moment_binding(
        self,
        command: MomentAssetBindingPrepareDTO | MomentAssetBindingCommitDTO,
        *,
        operation: str,
        suffix: str,
    ) -> MomentAssetBindingResultDTO:
        payload: dict[str, Any] = {
            "owner_user_id": command.owner_user_id,
            "scope_id": command.moment_id,
            "binding_client_id": command.client_moment_id,
        }
        if isinstance(command, MomentAssetBindingCommitDTO):
            payload["bound_resource_id"] = command.moment_id
        data = _mapping(
            await self._request_json(
                "POST",
                (
                    f"/v1/moment-assets/{quote(command.asset_id, safe='')}"
                    f"/bindings/{suffix}"
                ),
                operation=operation,
                json=payload,
            ),
            operation=operation,
            exact_keys=frozenset({"asset", "binding_status"}),
        )
        asset = _moment_asset_from_json(data["asset"], operation=operation)
        _assert_moment_asset_scope(
            asset,
            operation=operation,
            asset_id=command.asset_id,
            owner_user_id=command.owner_user_id,
            moment_id=command.moment_id,
        )
        binding_status = _string(data, "binding_status", operation=operation)
        allowed = {"committed"} if suffix == "commit" else {"prepared", "committed"}
        if binding_status not in allowed or asset.status != "active":
            raise ChatAssetStoreProtocolError(operation=operation)
        return MomentAssetBindingResultDTO(
            asset=asset,
            binding_status=binding_status,  # type: ignore[arg-type]
        )

    async def prepare_moment_binding(
        self,
        command: MomentAssetBindingPrepareDTO,
    ) -> MomentAssetBindingResultDTO:
        return await self._moment_binding(
            command,
            operation="prepare_moment_binding",
            suffix="prepare",
        )

    async def commit_moment_binding(
        self,
        command: MomentAssetBindingCommitDTO,
    ) -> MomentAssetBindingResultDTO:
        return await self._moment_binding(
            command,
            operation="commit_moment_binding",
            suffix="commit",
        )

    async def create_moment_download_intent(
        self,
        command: MomentAssetDownloadRequestDTO,
    ) -> ChatAssetDownloadIntentDTO:
        operation = "create_moment_download_intent"
        data = _mapping(
            await self._request_json(
                "POST",
                (
                    f"/v1/moment-assets/{quote(command.asset_id, safe='')}"
                    "/download-intents"
                ),
                operation=operation,
                json={
                    "owner_user_id": command.owner_user_id,
                    "reader_user_id": command.reader_user_id,
                    "scope_id": command.moment_id,
                    "bound_resource_id": command.moment_id,
                    "variant": command.variant,
                    "disposition": command.disposition,
                    "asset_version": command.asset_version,
                },
                accepted_statuses=frozenset({200, 201}),
            ),
            operation=operation,
            exact_keys=frozenset({"download_ticket", "expires_at"}),
        )
        ticket = _string(data, "download_ticket", operation=operation)
        if _TICKET_RE.fullmatch(ticket) is None:
            raise ChatAssetStoreProtocolError(operation=operation)
        return ChatAssetDownloadIntentDTO(
            opaque_ticket=ticket,
            expires_at=_timestamp(data, "expires_at", operation=operation),
        )

    async def inspect_scoped_transfer(
        self,
        *,
        opaque_ticket: str,
        direction: str,
        method: str,
    ) -> ScopedAssetTransferInspectionDTO:
        operation = "inspect_scoped_transfer"
        data = _mapping(
            await self._request_json(
                "POST",
                "/v2/transfers/inspect",
                operation=operation,
                json={
                    "ticket": opaque_ticket,
                    "direction": direction,
                    "method": method,
                },
            ),
            operation=operation,
            exact_keys=frozenset(
                {
                    "asset_id",
                    "owner_user_id",
                    "reader_user_id",
                    "usage",
                    "scope_id",
                    "bound_resource_id",
                    "variant",
                    "version",
                    "expires_at",
                }
            ),
        )
        asset_id = _string(data, "asset_id", operation=operation)
        owner_user_id = _string(data, "owner_user_id", operation=operation)
        usage = _string(data, "usage", operation=operation)
        scope_id = _string(data, "scope_id", operation=operation)
        reader_user_id = data.get("reader_user_id")
        bound_resource_id = data.get("bound_resource_id")
        variant = data.get("variant")
        if (
            _ASSET_ID_RE.fullmatch(asset_id) is None
            or usage not in {"chat_message", "moment_image"}
            or not scope_id
            or (usage == "moment_image" and _MOMENT_ID_RE.fullmatch(scope_id) is None)
        ):
            raise ChatAssetStoreProtocolError(operation=operation)
        if direction == "upload":
            if (
                method != "PUT"
                or reader_user_id is not None
                or bound_resource_id is not None
                or variant is not None
            ):
                raise ChatAssetStoreProtocolError(operation=operation)
        elif (
            direction != "download"
            or method not in {"GET", "HEAD"}
            or not isinstance(reader_user_id, str)
            or not reader_user_id
            or not isinstance(bound_resource_id, str)
            or not bound_resource_id
            or variant not in {"original", "thumbnail"}
            or (usage == "moment_image" and bound_resource_id != scope_id)
        ):
            raise ChatAssetStoreProtocolError(operation=operation)
        return ScopedAssetTransferInspectionDTO(
            asset_id=asset_id,
            owner_user_id=owner_user_id,
            reader_user_id=reader_user_id,
            usage=usage,  # type: ignore[arg-type]
            scope_id=scope_id,
            bound_resource_id=bound_resource_id,
            variant=variant,  # type: ignore[arg-type]
            version=_integer(data, "version", operation=operation, minimum=1),
            expires_at=_timestamp(data, "expires_at", operation=operation),
        )

    async def quarantine_asset(
        self,
        command: ChatAssetQuarantineCommandDTO,
    ) -> ChatAssetLifecycleResultDTO:
        operation = "quarantine_asset"
        result = self._lifecycle_result(
            await self._request_json(
                "POST",
                f"/v1/assets/{quote(command.asset_id, safe='')}/quarantine",
                operation=operation,
                json={
                    "requested_by_user_id": command.requested_by_user_id,
                    "reason": command.reason,
                    "requested_at": _iso(command.requested_at),
                },
            ),
            operation=operation,
        )
        if result.asset_id != command.asset_id or result.status != "quarantined":
            raise ChatAssetStoreProtocolError(operation=operation)
        return result

    async def delete_asset(
        self,
        command: ChatAssetDeleteCommandDTO,
    ) -> ChatAssetLifecycleResultDTO:
        operation = "delete_asset"
        result = self._lifecycle_result(
            await self._request_json(
                "POST",
                f"/v1/assets/{quote(command.asset_id, safe='')}/delete",
                operation=operation,
                json={
                    "requested_by_user_id": command.requested_by_user_id,
                    "reason": command.reason,
                    "requested_at": _iso(command.requested_at),
                },
            ),
            operation=operation,
        )
        if result.asset_id != command.asset_id or result.status not in {
            "delete_pending",
            "deleted",
        }:
            raise ChatAssetStoreProtocolError(operation=operation)
        return result

    @staticmethod
    def _lifecycle_result(
        raw: Any,
        *,
        operation: str,
    ) -> ChatAssetLifecycleResultDTO:
        data = _mapping(
            raw,
            operation=operation,
            exact_keys=frozenset({"asset_id", "status", "version"}),
        )
        asset_id = _string(data, "asset_id", operation=operation)
        status = _string(data, "status", operation=operation)
        if _ASSET_ID_RE.fullmatch(asset_id) is None or status not in {
            "quarantined",
            "delete_pending",
            "deleted",
        }:
            raise ChatAssetStoreProtocolError(operation=operation)
        return ChatAssetLifecycleResultDTO(
            asset_id=asset_id,
            status=status,  # type: ignore[arg-type]
            version=_integer(data, "version", operation=operation, minimum=1),
        )


def configured_chat_asset_capability() -> StorageCapabilityDescription:
    return StorageCapabilityDescription(
        store_name="chat_asset_store",
        status="configured",
        configured=True,
        readable=True,
        writable=True,
        durable=True,
        external_io_enabled=True,
        operations=tuple(
            dict.fromkeys(
                CHAT_ASSET_STORE_OPERATIONS + MOMENT_ASSET_STORE_OPERATIONS
            )
        ),
        reason="C19 asset service is configured for chat and Moment images.",
    )


__all__ = [
    "ASSET_STORE_TIMEOUT_ENV",
    "ASSET_STORE_TOKEN_ENV",
    "ASSET_STORE_URL_ENV",
    "ChatAssetStoreAuthenticationError",
    "ChatAssetStoreConflictError",
    "ChatAssetStoreHttpError",
    "ChatAssetStoreProtocolError",
    "ChatAssetStoreQuotaError",
    "ChatAssetStoreRejectedError",
    "ChatAssetStoreUnavailableError",
    "HttpChatAssetStore",
    "HttpChatAssetStoreConfig",
    "configured_chat_asset_capability",
]
