"""In-process secret update event bus for R System workers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Callable
from uuid import uuid4


SECRET_UPDATED = "SECRET_UPDATED"
SECRET_RELOAD_REQUESTED = "SECRET_RELOAD_REQUESTED"


@dataclass(frozen=True)
class SecretEvent:
    event_type: str
    org_id: str
    service: str | None = None
    source: str = "secret_manager"
    event_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


SecretEventHandler = Callable[[SecretEvent], None]


class SecretEventBus:
    """Synchronous pub/sub bus used by API writes and local worker runtimes."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._subscribers: dict[str, SecretEventHandler] = {}
        self._history: list[SecretEvent] = []

    def subscribe(self, handler: SecretEventHandler) -> str:
        token = str(uuid4())
        with self._lock:
            self._subscribers[token] = handler
        return token

    def unsubscribe(self, token: str) -> None:
        with self._lock:
            self._subscribers.pop(token, None)

    def publish(
        self,
        event_type: str,
        *,
        org_id: str,
        service: str | None = None,
        source: str = "secret_manager",
    ) -> SecretEvent:
        event = SecretEvent(
            event_type=event_type,
            org_id=org_id,
            service=service,
            source=source,
            event_id=str(uuid4()),
            created_at=datetime.now(UTC).isoformat(),
        )
        with self._lock:
            handlers = list(self._subscribers.values())
            self._history.append(event)
        for handler in handlers:
            handler(event)
        return event

    def history(self) -> list[SecretEvent]:
        with self._lock:
            return list(self._history)

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()
            self._history.clear()


secret_event_bus = SecretEventBus()


def publish_secret_updated(org_id: str, service: str, *, source: str = "secret_manager") -> SecretEvent:
    return secret_event_bus.publish(
        SECRET_UPDATED,
        org_id=org_id,
        service=service,
        source=source,
    )
