"""K19-B keyword persistence service.

This module manages human-editable KeywordEntry records in memory only. It does
not call AI providers, perform SEO analysis, run ranking systems, invoke
K17/K18 logic, implement API/UI layers, or target production/staging systems.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import uuid4

from .models import KeywordEntry, KeywordEntrySource, KeywordEntryStatus

K19_B_MODE = "persistence_only"
K19_RUNTIME = "no_execution"
K19_EXTERNAL_ACCESS = False

KEYWORD_STORE: dict[str, KeywordEntry] = {}

_PATCHABLE_FIELDS = {
    "keyword",
    "product_id",
    "source",
    "status",
}

_DEFAULT_STATUS_BY_SOURCE: dict[str, KeywordEntryStatus] = {
    "K15": "suggested",
    "K16": "suggested",
    "K17": "suggested",
    "K18": "active",
    "manual": "active",
}


class KeywordService:
    """CRUD facade for in-memory KeywordEntry persistence."""

    def __init__(self, store: dict[str, KeywordEntry] | None = None) -> None:
        self.store = KEYWORD_STORE if store is None else store

    def create(self, keyword_entry: KeywordEntry | Mapping[str, Any]) -> KeywordEntry:
        entry = self._validate_entry(keyword_entry)
        if entry.id in self.store:
            raise ValueError(f"keyword entry already exists: {entry.id}")
        self.store[entry.id] = entry
        return entry

    def create_from_source(
        self,
        product_id: str,
        keyword: str,
        source: KeywordEntrySource,
        keyword_id: str | None = None,
        status: KeywordEntryStatus | None = None,
    ) -> KeywordEntry:
        now = datetime.now(UTC)
        entry = KeywordEntry(
            id=keyword_id or str(uuid4()),
            product_id=product_id,
            keyword=keyword,
            source=source,
            status=status or _DEFAULT_STATUS_BY_SOURCE[str(source)],
            created_at=now,
            updated_at=now,
        )
        return self.create(entry)

    def bulk_create_from_source(
        self,
        product_id: str,
        keywords: list[str],
        source: KeywordEntrySource,
        status: KeywordEntryStatus | None = None,
    ) -> list[KeywordEntry]:
        entries: list[KeywordEntry] = []
        for keyword in keywords:
            if self._is_blank(keyword):
                continue
            entries.append(
                self.create_from_source(
                    product_id=product_id,
                    keyword=keyword,
                    source=source,
                    status=status,
                )
            )
        return entries

    def get(self, keyword_id: str) -> KeywordEntry | None:
        return self.store.get(self._clean_text(keyword_id))

    def get_by_product(self, product_id: str) -> list[KeywordEntry]:
        cleaned_product_id = self._clean_text(product_id)
        return [
            entry
            for entry in self.store.values()
            if entry.product_id == cleaned_product_id
        ]

    def update(
        self,
        keyword_id: str,
        data: Mapping[str, Any],
    ) -> KeywordEntry | None:
        existing_entry = self.get(keyword_id)
        if existing_entry is None:
            return None

        patch = {
            key: value
            for key, value in data.items()
            if key in _PATCHABLE_FIELDS and value is not None
        }
        if not patch:
            return existing_entry

        updated_entry = existing_entry.model_copy(
            update={
                **patch,
                "updated_at": datetime.now(UTC),
            }
        )
        validated_entry = KeywordEntry(**updated_entry.model_dump())
        self.store[existing_entry.id] = validated_entry
        return validated_entry

    def delete(self, keyword_id: str) -> KeywordEntry | None:
        existing_entry = self.get(keyword_id)
        if existing_entry is None:
            return None

        archived_entry = existing_entry.model_copy(
            update={
                "status": "archived",
                "updated_at": datetime.now(UTC),
            }
        )
        self.store[existing_entry.id] = archived_entry
        return archived_entry

    @staticmethod
    def _validate_entry(keyword_entry: KeywordEntry | Mapping[str, Any]) -> KeywordEntry:
        if isinstance(keyword_entry, KeywordEntry):
            return keyword_entry
        return KeywordEntry(**dict(keyword_entry))

    @staticmethod
    def _clean_text(value: object) -> str:
        return " ".join(str(value).strip().split())

    @staticmethod
    def _is_blank(value: object) -> bool:
        return not str(value).strip()


__all__ = [
    "KEYWORD_STORE",
    "K19_B_MODE",
    "K19_EXTERNAL_ACCESS",
    "K19_RUNTIME",
    "KeywordService",
]
