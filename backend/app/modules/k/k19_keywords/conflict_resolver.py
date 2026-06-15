"""K19-F keyword conflict resolution engine.

This module resolves KeywordEntry conflicts with deterministic human-first
rules only. It does not call AI providers, perform SEO analysis, run ranking
systems, mutate K19-A/B/C/D/E, access external APIs, or target
production/staging environments.
"""

from __future__ import annotations

from typing import Literal

from .models import KeywordEntry, KeywordEntrySource

K19_F_MODE = "conflict_resolution_only"
K19_RUNTIME = "no_execution"
K19_EXTERNAL_ACCESS = False

K19_F_DATA_FLOW = (
    "K15-K18 imported keywords",
    "manual keyword edits",
    "K19-F conflict resolution",
    "K19 final truth layer",
)

KeywordConflictType = Literal[
    "keyword_conflict",
    "source_conflict",
    "status_conflict",
]

CONFLICT_TYPES: tuple[KeywordConflictType, ...] = (
    "keyword_conflict",
    "source_conflict",
    "status_conflict",
)

SOURCE_PRIORITY: dict[str, int] = {
    "manual": 5,
    "K18": 4,
    "K17": 3,
    "K16": 2,
    "K15": 1,
}

HUMAN_OVERRIDE_STATUSES = {"archived", "edited"}


class KeywordConflictResolver:
    """Resolve keyword conflicts with human-first deterministic rules."""

    def resolve(
        self,
        ai_keyword: KeywordEntry | None,
        manual_keyword: KeywordEntry | None,
    ) -> KeywordEntry:
        if ai_keyword is None and manual_keyword is None:
            raise ValueError("at least one keyword entry is required")
        if ai_keyword is None:
            return self._require_entry(manual_keyword)
        if manual_keyword is None:
            return ai_keyword

        if self._is_human_override(manual_keyword):
            return manual_keyword

        if self.conflict_with(ai_keyword, manual_keyword):
            return manual_keyword

        if ai_keyword.source == "K18":
            return ai_keyword

        return self._higher_priority(ai_keyword, manual_keyword)

    def detect_conflicts(
        self,
        ai_keyword: KeywordEntry,
        manual_keyword: KeywordEntry,
    ) -> list[KeywordConflictType]:
        conflict_types: list[KeywordConflictType] = []

        if self._normalized_keyword(ai_keyword) != self._normalized_keyword(
            manual_keyword,
        ):
            conflict_types.append("keyword_conflict")

        if self._has_source_conflict(ai_keyword.source, manual_keyword.source):
            conflict_types.append("source_conflict")

        if self._has_status_conflict(ai_keyword.status, manual_keyword.status):
            conflict_types.append("status_conflict")

        return conflict_types

    def conflict_with(
        self,
        ai_keyword: KeywordEntry,
        manual_keyword: KeywordEntry,
    ) -> bool:
        return bool(self.detect_conflicts(ai_keyword, manual_keyword))

    def _higher_priority(
        self,
        first_entry: KeywordEntry,
        second_entry: KeywordEntry,
    ) -> KeywordEntry:
        first_priority = self._priority_for(first_entry.source)
        second_priority = self._priority_for(second_entry.source)
        if first_priority >= second_priority:
            return first_entry
        return second_entry

    @staticmethod
    def _is_human_override(keyword_entry: KeywordEntry) -> bool:
        return (
            keyword_entry.source == "manual"
            or keyword_entry.status in HUMAN_OVERRIDE_STATUSES
        )

    @staticmethod
    def _normalized_keyword(keyword_entry: KeywordEntry) -> str:
        return " ".join(keyword_entry.keyword.strip().lower().split())

    @staticmethod
    def _has_source_conflict(
        first_source: KeywordEntrySource,
        second_source: KeywordEntrySource,
    ) -> bool:
        sources = {str(first_source), str(second_source)}
        return "manual" in sources and "K18" in sources

    @staticmethod
    def _has_status_conflict(first_status: str, second_status: str) -> bool:
        statuses = {str(first_status), str(second_status)}
        return "active" in statuses and "archived" in statuses

    @staticmethod
    def _priority_for(source: KeywordEntrySource) -> int:
        return SOURCE_PRIORITY.get(str(source), 0)

    @staticmethod
    def _require_entry(keyword_entry: KeywordEntry | None) -> KeywordEntry:
        if keyword_entry is None:
            raise ValueError("keyword entry is required")
        return keyword_entry


__all__ = [
    "CONFLICT_TYPES",
    "HUMAN_OVERRIDE_STATUSES",
    "K19_EXTERNAL_ACCESS",
    "K19_F_DATA_FLOW",
    "K19_F_MODE",
    "K19_RUNTIME",
    "KeywordConflictResolver",
    "KeywordConflictType",
    "SOURCE_PRIORITY",
]
