"""霓旌的身份与环境开关。"""

from __future__ import annotations

import os

AGENT_ID = "mfg.nijing"
AGENT_USERNAME = "nijing"
AGENT_DISPLAY_NAME = "霓旌"
AGENT_JOB_TITLE = "库管员"
AGENT_BIO = "库管员 · 入库 / 生产 / 发货 / 盘点,跟我说一句就行"
ACTOR_TYPE = "agent"
PASSWORD_ENV = "NIJING_PASSWORD"
MEMORY_INDEX_TITLE = "霓旌的记忆"

CARD_TTL_SECONDS = 30 * 60
MESSAGE_LOOKBACK = 20

CONFIRM_WORDS = frozenset({"确认", "对", "好", "好的", "是", "是的", "可以", "ok", "okay", "yes", "没错", "确定", "执行", "嗯", "行"})
CANCEL_WORDS = frozenset({"取消", "不", "不要", "算了", "不对", "错了", "作废", "no", "cancel", "停"})


def poll_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("AGENT_CHAT_POLL_SECONDS", "3")))
    except ValueError:
        return 3.0


def ai_timeout_seconds() -> float:
    """聊天必须短超时(DeepSeek 有过单次 903 秒才返回)。默认 30s,下限 10s。"""
    try:
        return max(10.0, float(os.getenv("NIJING_AI_TIMEOUT_SECONDS", "30")))
    except ValueError:
        return 30.0
