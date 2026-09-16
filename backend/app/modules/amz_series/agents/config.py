"""amz-agents-worker 的运行参数(全部 env,默认值照白苏婉 / 霓旌)。"""

from __future__ import annotations

import os

REPORT_TIMEZONE = "America/Los_Angeles"
ACTOR_TYPE = "agent"
MESSAGE_LOOKBACK = 20


def poll_seconds() -> float:
    try:
        value = float(os.getenv("AMZ_AGENTS_POLL_SECONDS", os.getenv("AGENT_CHAT_POLL_SECONDS", "3")))
    except ValueError:
        return 3.0
    return max(1.0, value)


def patrol_seconds() -> float:
    try:
        value = float(os.getenv("AMZ_AGENTS_PATROL_SECONDS", "600"))
    except ValueError:
        return 600.0
    return max(60.0, value)


def patrol_enabled() -> bool:
    return os.getenv("AMZ_AGENTS_PATROL_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def report_to_user_ids() -> tuple[str, ...]:
    """主动消息发给谁。默认 owner(1)和王创鑫(2)——A 系列只对这两个人开放。"""
    raw = os.getenv("AMZ_AGENTS_REPORT_TO_USER_IDS", "1,2")
    return tuple(part.strip() for part in raw.split(",") if part.strip().isdigit()) or ("1",)


def speak_hours() -> tuple[int, int]:
    """主动开口只在老板醒着的时候(洛杉矶时间,含起点不含终点)。默认 08:00–22:00;深夜护睡是家规。"""
    raw = os.getenv("AMZ_AGENTS_SPEAK_HOURS", "8-22")
    try:
        start, end = (int(part) for part in raw.split("-", 1))
    except ValueError:
        return (8, 22)
    start, end = max(0, min(start, 23)), max(1, min(end, 24))
    return (start, end) if start < end else (8, 22)


def ai_timeout_seconds() -> float:
    try:
        value = float(os.getenv("AGENT_DEEPSEEK_TIMEOUT_SECONDS", "60"))
    except ValueError:
        return 60.0
    return max(10.0, value)


def heartbeat_interval_seconds() -> int:
    return 900
