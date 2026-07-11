"""HTTP adapter for the independently deployable C19 record service.

The adapter owns no message persistence.  It translates the provider-neutral
``ChatRecordStore`` contract into the versioned record-service API and rejects
missing, unreachable, or malformed providers without manufacturing a success.
"""

from __future__ import annotations

import os
from ipaddress import ip_address
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, NoReturn
from urllib.parse import quote, urlsplit

import httpx

from .storage import (
    CHAT_RECORD_STORE_OPERATIONS,
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
    ChatRetentionCommandDTO,
    ChatUnreadPositionDTO,
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


def _mapping(value: Any, *, operation: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
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


def _record_from_json(data: Any, *, operation: str) -> ChatRecordDTO:
    item = _mapping(data, operation=operation)
    status = _required_string(item, "status", operation=operation)
    if status not in {"sent", "delivered", "read"}:
        raise ChatRecordStoreProtocolError(operation=operation)
    content_type = _required_string(item, "content_type", operation=operation)
    if content_type not in {"text", "emoji"}:
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
        content=_required_string(item, "content", operation=operation),
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

    async def apply_retention(
        self,
        command: ChatRetentionCommandDTO,
    ) -> ChatRecordMutationResultDTO:
        operation = "apply_retention"
        return self._mutation_result(
            await self._request_json(
                "POST",
                "/v1/retention/apply",
                operation=operation,
                json={
                    "requested_by_user_id": command.requested_by_user_id,
                    "reason": command.reason,
                    "requested_at": _iso(command.requested_at),
                    "delete_before": _iso(command.delete_before),
                    "conversation_id": command.conversation_id,
                    "maximum_records": command.maximum_records,
                },
            ),
            operation=operation,
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
        operations=CHAT_RECORD_STORE_OPERATIONS,
        reason="C19 chat record service is configured.",
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
