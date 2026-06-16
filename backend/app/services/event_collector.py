from __future__ import annotations

import json
import logging
import queue
import threading
from collections import deque
from collections.abc import Mapping
from contextvars import Token, ContextVar
from typing import Any
from uuid import uuid4

from ..schemas.event_collector import (
    AuditEvent,
    EventModule,
    EventSource,
    EventStatus,
)

EVENT_LOGGER_NAME = "barong.audit_events"
DEFAULT_EVENT_BUFFER_SIZE = 5000
DEFAULT_EVENT_QUEUE_SIZE = 10000
MAX_STRING_LENGTH = 2000
SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "password_hash",
    "token",
    "secret",
    "session_id",
    "cookie",
    "set-cookie",
    "signature",
    "nonce",
    "idempotency",
    "authorization",
    "api_key",
    "private_key",
    "credential",
    "webhook_url",
    "provider_url",
    "endpoint",
)

_context_id: ContextVar[str | None] = ContextVar(
    "event_context_id",
    default=None,
)
_user_id: ContextVar[str | None] = ContextVar("event_user_id", default=None)
_product_key: ContextVar[str | None] = ContextVar(
    "event_product_key",
    default=None,
)
_workflow_id: ContextVar[str | None] = ContextVar(
    "event_workflow_id",
    default=None,
)


class EventEmitter:
    def __init__(
        self,
        *,
        buffer_size: int = DEFAULT_EVENT_BUFFER_SIZE,
        queue_size: int = DEFAULT_EVENT_QUEUE_SIZE,
    ) -> None:
        self._queue: queue.Queue[AuditEvent] = queue.Queue(maxsize=queue_size)
        self._recent_events: deque[AuditEvent] = deque(maxlen=buffer_size)
        self._lock = threading.Lock()
        self._dropped = 0
        self._emitted = 0
        self._started = False
        self._worker: threading.Thread | None = None
        self._logger = logging.getLogger(EVENT_LOGGER_NAME)

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._worker = threading.Thread(
                target=self._drain,
                name="barong-audit-event-emitter",
                daemon=True,
            )
            self._worker.start()
            self._started = True

    def emit(self, event: AuditEvent) -> bool:
        self.start()
        with self._lock:
            self._recent_events.append(event)
            self._emitted += 1

        try:
            self._queue.put_nowait(event)
        except queue.Full:
            with self._lock:
                self._dropped += 1
            return False
        return True

    def snapshot(self) -> list[AuditEvent]:
        with self._lock:
            return list(self._recent_events)

    def clear(self) -> None:
        with self._lock:
            self._recent_events.clear()
            self._dropped = 0
            self._emitted = 0
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            self._queue.task_done()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "buffered": len(self._recent_events),
                "queued": self._queue.qsize(),
                "emitted": self._emitted,
                "dropped": self._dropped,
            }

    def _drain(self) -> None:
        while True:
            event = self._queue.get()
            try:
                self._logger.info(
                    json.dumps(event.model_dump(mode="json"), sort_keys=True)
                )
            finally:
                self._queue.task_done()


DEFAULT_EVENT_EMITTER = EventEmitter()


def _truncate(value: str) -> str:
    if len(value) <= MAX_STRING_LENGTH:
        return value
    return f"{value[:MAX_STRING_LENGTH]}...[truncated]"


def sanitize_event_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(marker in normalized_key for marker in SENSITIVE_KEY_MARKERS):
                sanitized[str(key)] = "[redacted]"
                continue
            sanitized[str(key)] = sanitize_event_payload(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_event_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_event_payload(item) for item in value]
    if isinstance(value, str):
        return _truncate(value)
    return value


def generate_context_id() -> str:
    return str(uuid4())


def normalize_context_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if not candidate or len(candidate) > 128:
        return generate_context_id()
    lowered = candidate.lower()
    if any(marker in lowered for marker in SENSITIVE_KEY_MARKERS):
        return generate_context_id()
    return candidate


def current_context_id() -> str | None:
    return _context_id.get()


def set_current_event_context(
    *,
    context_id: str | None = None,
    user_id: str | None = None,
    product_key: str | None = None,
    workflow_id: str | None = None,
) -> dict[str, Token[str | None]]:
    tokens: dict[str, Token[str | None]] = {}
    if context_id is not None:
        tokens["context_id"] = _context_id.set(normalize_context_id(context_id))
    if user_id is not None:
        tokens["user_id"] = _user_id.set(user_id)
    if product_key is not None:
        tokens["product_key"] = _product_key.set(product_key)
    if workflow_id is not None:
        tokens["workflow_id"] = _workflow_id.set(workflow_id)
    return tokens


def reset_current_event_context(tokens: Mapping[str, Token[str | None]]) -> None:
    resetters = {
        "context_id": _context_id,
        "user_id": _user_id,
        "product_key": _product_key,
        "workflow_id": _workflow_id,
    }
    for key, token in tokens.items():
        resetters[key].reset(token)


def emit_event(
    *,
    event_type: str,
    module: EventModule = "system",
    action: str,
    source: EventSource = "backend",
    status: EventStatus = "success",
    context_id: str | None = None,
    user_id: str | None = None,
    product_key: str | None = None,
    workflow_id: str | None = None,
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    effective_context_id = normalize_context_id(context_id or _context_id.get())
    event = AuditEvent(
        event_type=event_type,
        module=module,
        action=action,
        context_id=effective_context_id,
        user_id=user_id if user_id is not None else _user_id.get(),
        product_key=(
            product_key if product_key is not None else _product_key.get()
        ),
        workflow_id=(
            workflow_id if workflow_id is not None else _workflow_id.get()
        ),
        source=source,
        status=status,
        latency_ms=max(latency_ms, 0),
        payload=sanitize_event_payload(dict(payload or {})),
        metadata=sanitize_event_payload(dict(metadata or {})),
    )
    DEFAULT_EVENT_EMITTER.emit(event)
    return event


def classify_module_from_path(path: str) -> EventModule:
    normalized = path.lower()
    if "/module-switch" in normalized or "/emergency-kill-switch" in normalized:
        return "C13"
    if any(
        marker in normalized
        for marker in (
            "/external-dependencies",
            "/dependency",
            "/ai-execution-bindings",
            "/model-locks",
            "/capability-bindings",
            "/module-allocations",
            "/execution-prompts",
        )
    ):
        return "C14"
    if any(
        marker in normalized
        for marker in (
            "/workflow",
            "/webhook-gateway",
            "/payload-standardization",
            "/callback-handler",
            "/result-normalization",
            "/failure-handling",
            "/n8n-test",
        )
    ):
        return "C15"
    if "/security" in normalized or "/control-plane" in normalized:
        return "C16"
    if "/products" in normalized or "/product" in normalized:
        return "Pxx"
    return "system"


def record_workflow_event(
    *,
    event_type: str,
    action: str,
    context_id: str,
    workflow_id: str | None,
    module_key: str | None = None,
    status: EventStatus = "success",
    source: EventSource = "n8n",
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type=event_type,
        module="C15",
        action=action,
        source=source,
        status=status,
        context_id=context_id,
        workflow_id=workflow_id,
        latency_ms=latency_ms,
        payload={"module": module_key, **dict(payload or {})},
        metadata=metadata,
    )


def record_llm_request(
    *,
    provider: str,
    model: str,
    context_id: str | None = None,
    prompt_input: Any = None,
    workflow_id: str | None = None,
    module: EventModule = "C14",
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type="ai.llm.request",
        module=module,
        action="llm.request",
        source="ai",
        status="pending",
        context_id=context_id,
        workflow_id=workflow_id,
        payload={
            "provider": provider,
            "model": model,
            "prompt_input": prompt_input,
        },
        metadata=metadata,
    )


def record_llm_response(
    *,
    provider: str,
    model: str,
    status: EventStatus,
    context_id: str | None = None,
    prompt_output: Any = None,
    token_usage: Mapping[str, Any] | None = None,
    workflow_id: str | None = None,
    latency_ms: float = 0,
    module: EventModule = "C14",
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type="ai.llm.response",
        module=module,
        action="llm.response",
        source="ai",
        status=status,
        context_id=context_id,
        workflow_id=workflow_id,
        latency_ms=latency_ms,
        payload={
            "provider": provider,
            "model": model,
            "prompt_output": prompt_output,
            "token_usage": dict(token_usage or {}),
        },
        metadata=metadata,
    )


def record_file_operation(
    *,
    action: str,
    storage_provider: str,
    storage_ref: str | None = None,
    status: EventStatus = "success",
    context_id: str | None = None,
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type=f"file.{action}",
        module="system",
        action=f"file.{action}",
        source="system",
        status=status,
        context_id=context_id,
        latency_ms=latency_ms,
        payload={
            "storage_provider": storage_provider,
            "storage_ref": storage_ref,
            **dict(payload or {}),
        },
        metadata=metadata,
    )


def record_filebrowser_operation(
    *,
    action: str,
    path: str | None = None,
    status: EventStatus = "success",
    context_id: str | None = None,
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return record_file_operation(
        action=action,
        storage_provider="FileBrowser",
        storage_ref=path,
        status=status,
        context_id=context_id,
        latency_ms=latency_ms,
        payload=payload,
        metadata=metadata,
    )


def record_minio_operation(
    *,
    action: str,
    object_key: str | None = None,
    bucket: str | None = None,
    status: EventStatus = "success",
    context_id: str | None = None,
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return record_file_operation(
        action=action,
        storage_provider="MinIO",
        storage_ref=object_key,
        status=status,
        context_id=context_id,
        latency_ms=latency_ms,
        payload={"bucket": bucket, **dict(payload or {})},
        metadata=metadata,
    )


def record_product_knowledge_event(
    *,
    action: str,
    status: EventStatus = "success",
    context_id: str | None = None,
    product_key: str | None = None,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type=f"product_knowledge.{action}",
        module="Pxx",
        action=f"product_knowledge.{action}",
        source="system",
        status=status,
        context_id=context_id,
        product_key=product_key,
        payload=payload,
        metadata=metadata,
    )


def get_event_buffer_snapshot() -> list[AuditEvent]:
    return DEFAULT_EVENT_EMITTER.snapshot()


def clear_event_buffer() -> None:
    DEFAULT_EVENT_EMITTER.clear()


def get_event_emitter_stats() -> dict[str, int]:
    return DEFAULT_EVENT_EMITTER.stats()
