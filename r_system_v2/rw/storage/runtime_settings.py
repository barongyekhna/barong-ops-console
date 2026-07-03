"""Runtime settings for the R-W realtime engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from r_system_v2.rw.providers.keepa_provider import MAX_REQUESTS_PER_MINUTE


SETTINGS_KEY = "rw_realtime_engine"


@dataclass(frozen=True)
class RwRuntimeSettings:
    deepseek_interval_seconds: int = 300
    deepseek_batch_size: int = 100
    deepseek_max_runtime_seconds: int = 240
    deepseek_schedule_enabled: bool = False
    deepseek_window_start: str = "01:00"
    deepseek_window_end: str = "05:00"
    deepseek_timezone: str = "Asia/Shanghai"
    keepa_batch_size: int = MAX_REQUESTS_PER_MINUTE
    discovery_categories_per_cycle: int = 1
    keepa_429_backoff_seconds: int = 300
    selected_categories: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_runtime_settings(db: Session) -> RwRuntimeSettings:
    try:
        row = db.execute(
            text("SELECT value FROM rw_runtime_settings WHERE key = :key"),
            {"key": SETTINGS_KEY},
        ).mappings().first()
    except SQLAlchemyError:
        db.rollback()
        return RwRuntimeSettings()
    if not row:
        return RwRuntimeSettings()
    return normalize_runtime_settings(row.get("value"))


def save_runtime_settings(
    db: Session,
    payload: dict[str, Any],
) -> RwRuntimeSettings:
    existing = load_runtime_settings(db).to_dict()
    settings = normalize_runtime_settings({**existing, **payload})
    value = json.dumps(settings.to_dict(), ensure_ascii=False)
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
            {"key": SETTINGS_KEY, "value": value},
        )
    else:
        updated = db.execute(
            text(
                """
                UPDATE rw_runtime_settings
                SET value = :value,
                    updated_at = CURRENT_TIMESTAMP
                WHERE key = :key
                """
            ),
            {"key": SETTINGS_KEY, "value": value},
        )
        if not updated.rowcount:
            db.execute(
                text(
                    """
                    INSERT INTO rw_runtime_settings (key, value, updated_at)
                    VALUES (:key, :value, CURRENT_TIMESTAMP)
                    """
                ),
                {"key": SETTINGS_KEY, "value": value},
            )
    return settings


def normalize_runtime_settings(payload: Any) -> RwRuntimeSettings:
    if isinstance(payload, str) and payload.strip():
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    data = payload if isinstance(payload, dict) else {}
    return RwRuntimeSettings(
        deepseek_interval_seconds=_bounded_int(
            data.get("deepseek_interval_seconds"),
            default=300,
            minimum=60,
            maximum=86_400,
        ),
        deepseek_batch_size=_bounded_int(
            data.get("deepseek_batch_size"),
            default=100,
            minimum=1,
            maximum=2_000,
        ),
        deepseek_max_runtime_seconds=_bounded_int(
            data.get("deepseek_max_runtime_seconds"),
            default=240,
            minimum=10,
            maximum=3_600,
        ),
        deepseek_schedule_enabled=_bool_value(
            data.get("deepseek_schedule_enabled"),
            default=False,
        ),
        deepseek_window_start=_time_value(
            data.get("deepseek_window_start"),
            default="01:00",
        ),
        deepseek_window_end=_time_value(
            data.get("deepseek_window_end"),
            default="05:00",
        ),
        deepseek_timezone=_timezone_value(data.get("deepseek_timezone")),
        keepa_batch_size=_bounded_int(
            data.get("keepa_batch_size"),
            default=MAX_REQUESTS_PER_MINUTE,
            minimum=1,
            maximum=MAX_REQUESTS_PER_MINUTE,
        ),
        discovery_categories_per_cycle=_bounded_int(
            data.get("discovery_categories_per_cycle"),
            default=1,
            minimum=1,
            maximum=20,
        ),
        keepa_429_backoff_seconds=_bounded_int(
            data.get("keepa_429_backoff_seconds"),
            default=300,
            minimum=60,
            maximum=86_400,
        ),
        selected_categories=_optional_string_list(data.get("selected_categories"))
        if "selected_categories" in data
        else None,
    )


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _optional_string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    cleaned: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _bool_value(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _time_value(value: Any, *, default: str) -> str:
    text = str(value or "").strip()
    if len(text) == 5 and text[2] == ":":
        hour, minute = text.split(":", 1)
        if hour.isdigit() and minute.isdigit():
            parsed_hour = int(hour)
            parsed_minute = int(minute)
            if 0 <= parsed_hour <= 23 and 0 <= parsed_minute <= 59:
                return f"{parsed_hour:02d}:{parsed_minute:02d}"
    return default


def _timezone_value(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"Asia/Shanghai", "UTC"}:
        return text
    return "Asia/Shanghai"
