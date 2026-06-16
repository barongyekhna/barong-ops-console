"""K21-E snapshot builder derived from K operation logs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import KOperationLog
from .query import KOperationLogQuery

K21_E_MODE = "snapshot_from_logs"
K21_SNAPSHOT_MUTATION = False
K21_EXTERNAL_ACCESS = False


class KSystemSnapshotBuilder:
    """Rebuilds K-system state from read-only query results."""

    def __init__(self, query_layer: KOperationLogQuery) -> None:
        self.query = query_layer

    def rebuild_k19_state(self) -> dict[str, dict[str, Any]]:
        logs = self.query.by_event_type("K19")
        return self._reduce_state(logs)

    def rebuild_k20_state(self) -> dict[str, dict[str, Any]]:
        logs = self.query.by_event_type("K20")
        return self._reduce_state(logs)

    def rebuild_k23_state(self) -> dict[str, dict[str, Any]]:
        logs = self.query.by_event_type("K23")
        return self._reduce_state(logs)

    def build_timeline(self) -> list[KOperationLog]:
        return sorted(self.query.logs, key=lambda log: (log.timestamp, log.log_id))

    def _reduce_state(self, logs: list[KOperationLog]) -> dict[str, dict[str, Any]]:
        state: dict[str, dict[str, Any]] = {}
        ordered_logs = sorted(logs, key=lambda log: (log.timestamp, log.log_id))

        for log in ordered_logs:
            if log.action == "delete":
                state.pop(log.entity_id, None)
                continue

            if log.after_state is not None:
                state[log.entity_id] = deepcopy(log.after_state)

        return state


__all__ = [
    "K21_E_MODE",
    "K21_EXTERNAL_ACCESS",
    "K21_SNAPSHOT_MUTATION",
    "KSystemSnapshotBuilder",
]
