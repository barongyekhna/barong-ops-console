"""K21-B in-memory append-only writer for K operation logs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import KOperationLog

K21_B_MODE = "append_only"
K21_MUTATION = False
K21_EXTERNAL_ACCESS = False
K21_ALLOWED_EVENT_TYPES = ("K19", "K20", "K23", "K24")


class KOperationLogWriter:
    """Append-only in-memory writer for K operation log entries."""

    def __init__(self) -> None:
        self.logs: list[KOperationLog] = []

    def append(self, log: KOperationLog) -> None:
        self._validate_k_event_type(log.event_type)
        self.logs.append(log)

    def update_event(self, log_id: str, new_state: dict[str, Any]) -> None:
        correction_log = KOperationLog(
            log_id=f"{log_id}_fix",
            event_type="K19",
            entity_type="module",
            entity_id=log_id,
            action="update",
            before_state=None,
            after_state=new_state,
            timestamp=datetime.utcnow(),
        )

        self.logs.append(correction_log)

    def batch_append(self, logs: list[KOperationLog]) -> None:
        for log in logs:
            self.append(log)

    def _validate_k_event_type(self, event_type: str) -> None:
        if event_type not in K21_ALLOWED_EVENT_TYPES:
            raise Exception("event_type must be K19, K20, K23, or K24")


__all__ = [
    "K21_ALLOWED_EVENT_TYPES",
    "K21_B_MODE",
    "K21_EXTERNAL_ACCESS",
    "K21_MUTATION",
    "KOperationLogWriter",
]
