"""苏青禾的身份与环境开关。"""

from __future__ import annotations

import os
from zoneinfo import ZoneInfo

AGENT_ID = "ops.suqinghe"
AGENT_USERNAME = "suqinghe"
AGENT_DISPLAY_NAME = "苏青禾"
AGENT_JOB_TITLE = "独立站运营总管"
# 性格一律不上前端(家规,见殷乐乐):简介只写职位。
AGENT_BIO = "独立站运营总管"
PASSWORD_ENV = "SUQINGHE_PASSWORD"
WORKER_NAME = "suqinghe-worker"
MODULE_KEY = "agent.suqinghe"
# 台账里她的花费记在这个名下(ai_usage_ledger.module)。
USAGE_LABEL = "suqinghe"
LA = ZoneInfo("America/Los_Angeles")

# 心跳间隔:worker 每 60 秒一轮,心跳按 120 秒算,3 倍(6 分钟)没动静判「掉线」。
HEARTBEAT_INTERVAL_SECONDS = 120
THINKING_FRESH_SECONDS = 120
NIGHT_START_HOUR = 22
NIGHT_END_HOUR = 8
MORNING_HOUR = 7
MAX_CARDS_PER_DAY = 5

CARD_STATUSES = ("pending", "approved", "rejected", "stale", "expired")
CARD_CHANNELS = ("web", "c19", "mcp")
MEMORY_KINDS = ("plan", "suggestion", "decision", "note", "dictation", "observation")
GOAL_STATUSES = ("active", "paused", "done", "dropped")
OFFICE_STATES = ("working", "thinking", "raised", "night", "offline")
DOSSIER_STATUSES = ("queued", "fetching", "reading", "ready", "blocked", "failed", "created", "rejected")
# 还在处理中的档案:同一个 offer 再交一次,不重复排队。
DOSSIER_ACTIVE_STATUSES = ("queued", "fetching", "reading", "ready")
DOSSIER_CARD_KIND = "create_k_dossier"


def dossier_daily_limit() -> int:
    """1688 每天最多开几个链接(匿名访问,频率高了会被 baxia 拦)。"""
    try:
        return max(0, int(os.getenv("SQH_1688_DAILY_LIMIT", "30")))
    except ValueError:
        return 30


DOSSIER_MIN_GAP_SECONDS = 60
DOSSIER_IMAGE_BUDGET_USD = 0.5


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def daily_claude_budget_usd() -> float:
    """她自己每天最多花多少 Claude(全局 $6.4 总闸之外再加一道)。超了改用 bulk 档。"""
    return max(0.0, _env_float("SQH_DAILY_CLAUDE_USD", 2.0))


def loop_seconds() -> float:
    return max(5.0, _env_float("SQH_LOOP_SECONDS", 60.0))
