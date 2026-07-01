"""ASIN ingestion utilities for Warehouse mock and production paths."""

from __future__ import annotations

import hashlib
import re

from r_system_v2.rw.core.models import IngestionRecord


ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


def is_asin(value: str) -> bool:
    return bool(ASIN_RE.match(value.strip().upper()))


def _mock_asin_from_query(query: str) -> str:
    digest = hashlib.sha1(query.strip().lower().encode("utf-8")).hexdigest().upper()
    return f"B0{digest[:8]}"


def build_ingestion_records(value: str | list[str], marketplace: str = "US") -> list[IngestionRecord]:
    """Normalize ASIN or search-query input into discovered ASIN records."""

    if isinstance(value, str):
        raw_values = [value]
    else:
        raw_values = value

    records: list[IngestionRecord] = []
    for raw_value in raw_values:
        cleaned = raw_value.strip()
        if not cleaned:
            continue
        asin = cleaned.upper() if is_asin(cleaned) else _mock_asin_from_query(cleaned)
        records.append(IngestionRecord(asin=asin, source_query=cleaned, marketplace=marketplace))
    return records

