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


def ai_timeout_seconds() -> float:
    try:
        value = float(os.getenv("AGENT_DEEPSEEK_TIMEOUT_SECONDS", "60"))
    except ValueError:
        return 60.0
    return max(10.0, value)


def heartbeat_interval_seconds() -> int:
    return 900
