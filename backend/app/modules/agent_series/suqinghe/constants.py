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
# 早间计划出的卡(brain.PLAN_FORMAT 里的 kind 加上 plan)。只有这几种按「快照里那件事」去重、对账(cards.settle_issues);
# 档案卡按档案号管,K 流水线的卡(pipeline.py)按产品和步骤管。
PLAN_CARD_KINDS = ("product_blocker", "plan", "ops_alert", "goal", "other")


def dossier_daily_limit() -> int:
    """1688 每天最多开几个链接(匿名访问,频率高了会被 baxia 拦)。"""
    try:
        return max(0, int(os.getenv("SQH_1688_DAILY_LIMIT", "30")))
    except ValueError:
        return 30


DOSSIER_MIN_GAP_SECONDS = 60
DOSSIER_IMAGE_BUDGET_USD = 0.5

# 第②步补完(10-27):K 写完文案她先读稿改稿,再发「文案卡」给老板看全文;驳了按老板的意见改。
COPY_CARD_KIND = "k_copy"


def image_brief_paused() -> bool:
    """作图指令那一段先停(10-27 老板拍板:他另有打算)。文案批了就停在那,等开关放开再接着出作图指令、出图。"""
    return os.getenv("SQH_IMAGE_BRIEF_PAUSED", "1").strip().lower() not in {"0", "false", "no", "off", ""}


# 第⑥步:她自己找货。先从 F 系列(找货页)的候选池里挑,一天最多发几张「选品」卡;老板没处理的攒到上限就不再发。
CANDIDATE_CARD_KIND = "candidate"
# 竞品拆解卡(10-27):建档后跑关键词前,她读同类商品页拆出来的市场情报;给老板看,不用批,驳了撤掉重跑关键词。
MARKET_CARD_KIND = "market"
# 工厂能力(选品评分「和工厂的关系」那一维她照这个判;老板改一句话就能换)。
FACTORY_BRIEF = (
    "我们在吉林有自己的工厂:无固定品类,擅长组装(把外购零部件装成成品)、换外观(颜色/贴牌/包装)、做套装(几件配成一套);"
    "注塑、冲压、电子件靠外协。能自己组装或配套的品比纯转卖值钱——以后能改款、能控成本。"
)


def pick_min_score() -> int:
    """选品评分卡过线分(满分 100),低于它的不发卡。"""
    try:
        return max(0, min(100, int(os.getenv("SQH_PICK_MIN_SCORE", "60"))))
    except ValueError:
        return 60


def weight_class_kg() -> dict[str, float]:
    """F 池里没有真重量:按她判的轻/中/重估个计费重算运费(卡上写明是估的)。"""
    out = {"light": 0.3, "medium": 1.0, "heavy": 2.5}
    for key in out:
        raw = os.getenv(f"SQH_WEIGHT_{key.upper()}_KG", "").strip()
        if raw:
            try:
                out[key] = max(0.05, float(raw))
            except ValueError:
                pass
    return out


def market_enabled() -> bool:
    """竞品拆解这一步的总开关(默认开)。关了流水线直接跳过这一步。"""
    return os.getenv("SQH_MARKET_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def market_pages() -> int:
    """一次拆解最多读几家同类商品页。"""
    try:
        return max(3, min(12, int(os.getenv("SQH_MARKET_PAGES", "8"))))
    except ValueError:
        return 8


def page_gap_seconds() -> float:
    """两页之间隔多久(别像爬虫一样连打)。"""
    return max(0.0, _env_float("SQH_PAGE_GAP_SECONDS", 3.0))


def picks_per_day() -> int:
    try:
        return max(0, int(os.getenv("SQH_PICKS_PER_DAY", "3")))
    except ValueError:
        return 3


def picks_max_pending() -> int:
    try:
        return max(1, int(os.getenv("SQH_PICKS_MAX_PENDING", "6")))
    except ValueError:
        return 6


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
