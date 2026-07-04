"""Durable Keepa discovery cursors for the R-W realtime worker."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


DISCOVERY_STATE_KEY = "rw_keepa_discovery_state"
DISCOVERY_STATE_VERSION = 1


def load_discovery_cursor(db: Session, category_id: str) -> int:
    state = _load_state(db)
    pages = state.get("category_pages")
    if not isinstance(pages, dict):
        return 0
    raw_value = pages.get(str(category_id))
    try:
        return max(0, int(raw_value))
    except (TypeError, ValueError):
        return 0


def save_discovery_cursor(db: Session, category_id: str, cursor: int) -> None:
    state = _load_state(db)
    pages = state.get("category_pages")
    if not isinstance(pages, dict):
        pages = {}
    pages[str(category_id)] = max(0, int(cursor))
    state = {
        "version": DISCOVERY_STATE_VERSION,
        "category_pages": pages,
    }
    _save_state(db, state)


def _load_state(db: Session) -> dict[str, Any]:
    try:
        row = db.execute(
            text("SELECT value FROM rw_runtime_settings WHERE key = :key"),
            {"key": DISCOVERY_STATE_KEY},
        ).mappings().first()
    except SQLAlchemyError:
        db.rollback()
        return {"version": DISCOVERY_STATE_VERSION, "category_pages": {}}
    if not row:
        return {"version": DISCOVERY_STATE_VERSION, "category_pages": {}}
    value = row.get("value")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {}
    if not isinstance(value, dict):
        value = {}
    pages = value.get("category_pages")
    return {
        "version": DISCOVERY_STATE_VERSION,
        "category_pages": pages if isinstance(pages, dict) else {},
    }


def _save_state(db: Session, state: dict[str, Any]) -> None:
    value = json.dumps(state, ensure_ascii=False)
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text(
                """
                INSERT INTO rw_runtime_settings (key, value, updated_at)
                VALUES (:key, CAST(:value AS JSONB), CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE SET
                  value = EXCLUDED.value,
                  updated_at = EXCLUDED.updated_at
                """
            ),
            {"key": DISCOVERY_STATE_KEY, "value": value},
        )
        return

    updated = db.execute(
        text(
            """
            UPDATE rw_runtime_settings
            SET value = :value,
                updated_at = CURRENT_TIMESTAMP
            WHERE key = :key
            """
        ),
        {"key": DISCOVERY_STATE_KEY, "value": value},
    )
    if not updated.rowcount:
        db.execute(
            text(
                """
                INSERT INTO rw_runtime_settings (key, value, updated_at)
                VALUES (:key, :value, CURRENT_TIMESTAMP)
                """
            ),
            {"key": DISCOVERY_STATE_KEY, "value": value},
        )
