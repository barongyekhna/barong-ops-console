"""主动开口的四条规矩(用户 2026-08-21 拍板,白苏婉先例),每名员工各自一份状态:

    出事就说 · 只报要人拍板的事 · 一天最多一条 · 同一件事永不重提

在 A 系列里「要人拍板的事」= 自己名下 severity=bad 的 open 建议。warn/info 留在浮窗里等人来看,
不打断人。门槛写在代码里不写在提示词里:不在名单里的事根本走不到发消息那一步。
「一天」按老板的日历(洛杉矶)算;深夜不开口(默认 08:00–22:00 之外一律等到早上)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import REPORT_TIMEZONE, speak_hours

STATE_NAME = "speech"
MAX_REMEMBERED_KEYS = 500
SPEAK_SEVERITIES = ("bad",)


def empty_state() -> dict[str, Any]:
    return {"reported_keys": {}, "last_spoke_date": None, "mute_until": None}


def normalize_state(raw: Any) -> dict[str, Any]:
    state = raw if isinstance(raw, dict) else empty_state()
    state.setdefault("reported_keys", {})
    state.setdefault("last_spoke_date", None)
    state.setdefault("mute_until", None)
    if not isinstance(state["reported_keys"], dict):
        state["reported_keys"] = {}
    return state


def local_today(now: datetime | None = None) -> str:
    moment = now or datetime.now(ZoneInfo(REPORT_TIMEZONE))
    return moment.astimezone(ZoneInfo(REPORT_TIMEZONE)).date().isoformat()


def local_hour(now: datetime | None = None) -> int:
    moment = now or datetime.now(ZoneInfo(REPORT_TIMEZONE))
    return moment.astimezone(ZoneInfo(REPORT_TIMEZONE)).hour


def is_awake_hour(hour: int | None = None) -> bool:
    start, end = speak_hours()
    return start <= (local_hour() if hour is None else hour) < end


def may_speak(state: dict[str, Any], *, today: str | None = None, hour: int | None = None) -> bool:
    if not is_awake_hour(hour):
        return False
    today = today or local_today()
    mute_until = state.get("mute_until")
    if isinstance(mute_until, str) and mute_until >= today:
        return False
    return state.get("last_spoke_date") != today


def pick_one(suggestions: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any] | None:
    """只挑最要紧的一件,其余留着等人问。刻意不打包——三件事一条消息 = 三个决定,那正是压垮人的东西。"""
    reported = state.get("reported_keys") or {}
    fresh = [s for s in suggestions if s.get("severity") in SPEAK_SEVERITIES and str(s.get("id")) not in reported]
    if not fresh:
        return None
    fresh.sort(key=lambda s: (s.get("store_code") or "", s.get("created_at") or ""))
    return fresh[0]


def mark_spoke(state: dict[str, Any], suggestion_id: str, *, today: str | None = None) -> None:
    state["last_spoke_date"] = today or local_today()
    keys = state.setdefault("reported_keys", {})
    keys[str(suggestion_id)] = datetime.now(UTC).isoformat()
    if len(keys) > MAX_REMEMBERED_KEYS:
        newest = sorted(keys.items(), key=lambda kv: str(kv[1]), reverse=True)
        state["reported_keys"] = dict(newest[:MAX_REMEMBERED_KEYS])


def set_mute(state: dict[str, Any], days: int, *, today: str | None = None) -> str:
    days = max(1, min(int(days), 30))
    base = datetime.fromisoformat(today) if today else datetime.now(ZoneInfo(REPORT_TIMEZONE))
    state["mute_until"] = (base.date() + timedelta(days=days - 1)).isoformat()
    return state["mute_until"]


__all__ = [
    "SPEAK_SEVERITIES",
    "STATE_NAME",
    "empty_state",
    "is_awake_hour",
    "local_hour",
    "local_today",
    "mark_spoke",
    "may_speak",
    "normalize_state",
    "pick_one",
    "set_mute",
]
