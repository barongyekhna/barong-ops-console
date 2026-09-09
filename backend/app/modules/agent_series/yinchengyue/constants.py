"""殷承岳的身份与环境开关。"""

from __future__ import annotations

import os

AGENT_ID = "product.yinchengyue"
AGENT_USERNAME = "yinchengyue"
AGENT_DISPLAY_NAME = "殷承岳"
AGENT_JOB_TITLE = "产品助理"
# 这段就是 C19 资料里的简介(≤255 字),要让人一眼知道他干什么、不干什么。
AGENT_BIO = (
    "产品助理 · 只做一件事:告诉你一个产品属于谷歌类目树里的哪个类目。"
    "把产品名 / 材质 / 用途 / 1688 标题发我(中英文都行,一次一个),"
    "我回英文类目名 + 理由,类目名可一键复制。"
    "我不改类目、不建产品、不做任何写入,谁都可以问。"
)
ACTOR_TYPE = "agent"
PASSWORD_ENV = "YINCHENGYUE_PASSWORD"
MEMORY_INDEX_TITLE = "殷承岳的记忆"
WORKER_NAME = "yinchengyue-worker"
MODULE_KEY = "agent.yinchengyue"

MESSAGE_LOOKBACK = 20
SHORTLIST_LIMIT = 25
MAX_KEYWORDS = 6
MAX_ANSWERED_KEEP = 2000
MAX_REASON_CHARS = 300


def poll_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("AGENT_CHAT_POLL_SECONDS", "3")))
    except ValueError:
        return 3.0


def ai_timeout_seconds() -> float:
    """一次判定要跑两次 flash,每次给 25 秒;DeepSeek 有过单次 903 秒才返回的记录。下限 10s。"""
    try:
        return max(10.0, float(os.getenv("YINCHENGYUE_AI_TIMEOUT_SECONDS", "25")))
    except ValueError:
        return 25.0
