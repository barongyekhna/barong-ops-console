"""K21-D read-only query layer for K operation logs."""

from __future__ import annotations

from datetime import datetime

from .models import KOperationLog

K21_D_MODE = "read_only_query"
K21_QUERY_MUTATION = False
K21_EXTERNAL_ACCESS = False


class KOperationLogQuery:
    """Deterministic filters over a supplied operation log list."""

    def __init__(self, logs: list[KOperationLog]) -> None:
        self.logs = logs

    def by_entity_id(self, entity_id: str) -> list[KOperationLog]:
        return [
            log
            for log in self.logs
            if log.entity_id == entity_id
        ]

    def by_event_type(self, event_type: str) -> list[KOperationLog]:
        return [
            log
            for log in self.logs
            if log.event_type == event_type
        ]

    def by_time_range(
        self,
        start: datetime,
        end: datetime,
    ) -> list[KOperationLog]:
        return [
            log
            for log in self.logs
            if start <= log.timestamp <= end
        ]

    def by_module(self, module: str) -> list[KOperationLog]:
        return [
            log
            for log in self.logs
            if log.event_type == module
        ]


__all__ = [
    "K21_D_MODE",
    "K21_EXTERNAL_ACCESS",
    "K21_QUERY_MUTATION",
    "KOperationLogQuery",
]
