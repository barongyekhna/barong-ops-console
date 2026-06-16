"""K21-C hooks that append K operation logs through the writer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import KOperationLog
from .writer import KOperationLogWriter

K21_C_MODE = "k_hooks_only"
K21_EXTERNAL_ACCESS = False


class KSystemHooks:
    """K-series hook layer for append-only operation log creation."""

    def __init__(self, writer: KOperationLogWriter) -> None:
        self.writer = writer
        self._log_sequence = 0

    def on_k19_update(
        self,
        entity_id: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        self._append_log(
            event_type="K19",
            entity_type="keyword",
            entity_id=entity_id,
            action="update",
            before=before,
            after=after,
        )

    def on_k20_update(
        self,
        entity_id: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        self._append_log(
            event_type="K20",
            entity_type="risk",
            entity_id=entity_id,
            action="update",
            before=before,
            after=after,
        )

    def on_k23_toggle(
        self,
        flag_key: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        self._append_log(
            event_type="K23",
            entity_type="flag",
            entity_id=flag_key,
            action="toggle",
            before=before,
            after=after,
        )

    def on_k24_module_change(
        self,
        module_key: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        self._append_log(
            event_type="K24",
            entity_type="module",
            entity_id=module_key,
            action="update",
            before=before,
            after=after,
        )

    def _append_log(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        log = KOperationLog(
            log_id=self._generate_id(event_type, entity_id, action),
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before_state=before,
            after_state=after,
            timestamp=self._now(),
        )
        self.writer.append(log)

    def _generate_id(self, event_type: str, entity_id: str, action: str) -> str:
        self._log_sequence += 1
        return f"{event_type}_{entity_id}_{action}_{self._log_sequence}"

    def _now(self) -> datetime:
        return datetime.utcnow()


__all__ = [
    "K21_C_MODE",
    "K21_EXTERNAL_ACCESS",
    "KSystemHooks",
]
