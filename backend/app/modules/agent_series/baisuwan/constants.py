"""白苏婉的固定身份与运行参数。"""

from __future__ import annotations

import os

AGENT_ID = "content.baisuwan"
AGENT_USERNAME = "baisuwan"
AGENT_DISPLAY_NAME = "白苏婉"
AGENT_JOB_TITLE = "内容专员"
AGENT_BIO = "内容专员 · 管 GEO 指南 / SEO 文章 / 内链网"

# 只读权限。第一版就这两条,一条写权限都不给。
AGENT_PERMISSIONS = (
    "geo.content.read",
    "seo.content.read",
)

# operation_log 里的身份。actor_type 无枚举约束,但既有先例是 demo_agent /
# test_agent,所以数字员工统一用 "agent",靠 actor_id 区分是哪一位。
ACTOR_TYPE = "agent"

MEMORY_ROOT_ENV = "AGENT_MEMORY_DIR"
DEFAULT_MEMORY_ROOT = "/var/lib/barong/agent-memory"


def memory_root() -> str:
    return os.getenv(MEMORY_ROOT_ENV, DEFAULT_MEMORY_ROOT)


def poll_seconds() -> float:
    try:
        value = float(os.getenv("AGENT_CHAT_POLL_SECONDS", "3"))
    except ValueError:
        return 3.0
    return max(1.0, value)


def console_base_url() -> str:
    return os.getenv("AGENT_CONSOLE_BASE_URL", "http://console_backend:8000").rstrip("/")


def agent_password() -> str | None:
    return os.getenv("BAISUWAN_PASSWORD") or None


def ai_timeout_seconds() -> float:
    """聊天窗口不能等 240 秒(路由器默认)。"""
    try:
        value = float(os.getenv("AGENT_DEEPSEEK_TIMEOUT_SECONDS", "60"))
    except ValueError:
        return 60.0
    return max(10.0, value)


# ---------- 主动巡检 ----------
#
# 她主动开口的规矩是用户拍板的,写进代码不写进提示词:
#   出事就说 · 只报「卡住」和「等审」· 一天最多一条 · 同一件事永不重提
#
# 为什么门槛这么严:用户当初否掉通知系统的原话是「按通知发消息会非常乱」。
# 主动消息一旦放开,三天就退化成刷屏的通知系统 —— 而且比通知更糟,聊天窗
# 没法忽略。所以判据只有一条:**这条消息他看完之后,需要动手或改主意吗?**


def patrol_seconds() -> float:
    """多久巡检一次。任务不会 3 秒完成一批,不必跟聊天同频。"""
    try:
        value = float(os.getenv("AGENT_PATROL_SECONDS", "600"))
    except ValueError:
        return 600.0
    return max(60.0, value)


def patrol_enabled() -> bool:
    return os.getenv("AGENT_PATROL_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def report_to_user_id() -> str:
    """主动消息发给谁。默认 owner(user 1)。"""
    return os.getenv("AGENT_REPORT_TO_USER_ID", "1").strip() or "1"


def stale_days() -> int:
    """多久没动算「卡住」。"""
    try:
        return max(1, int(os.getenv("AGENT_STALE_DAYS", "5")))
    except ValueError:
        return 5


# 老板在洛杉矶,「一天一条」按太平洋时间算,不按 UTC —— 否则他的下午会被
# 当成第二天,一天挨两条。
REPORT_TIMEZONE = "America/Los_Angeles"
