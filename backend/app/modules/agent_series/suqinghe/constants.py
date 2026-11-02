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
# needs_human(10-28):1688 要验证,页面在她的登录浏览器里留着,等老板过滑块/扫码;过了她自己接着做。
DOSSIER_STATUSES = ("queued", "fetching", "reading", "ready", "blocked", "failed", "created", "rejected", "needs_human")
# 还在处理中的档案:同一个 offer 再交一次,不重复排队。
DOSSIER_ACTIVE_STATUSES = ("queued", "fetching", "reading", "ready", "needs_human", "gate_ask")  # gate_ask:合规门清单外、等老板定(11-02)
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
# 运营看板(10-30):周报一张「只看不用批」的卡;日报不发卡,异常走 ops_alert(issue 前缀 ops:),一天最多 DIGEST_ALERTS_PER_DAY 张
DIGEST_CARD_KIND = "ops_digest"
DIGEST_ALERTS_PER_DAY = 2
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
    """她自己每天最多花多少 Claude。超了改用 bulk 档。

    11-02 老板定:按比例,不写死——「原来每天 6.5,苏青禾占 2,意味着苏青禾占总台账的 30%,我们可以依据动态配额,
    保证苏青禾还是这个比例就行」。= 两把钥匙今天总可花额度 × SQH_CLAUDE_SHARE_PCT(默认 30%)。
    额度表读不到、或还没登记额度(legacy)时,退回 SQH_DAILY_CLAUDE_USD(默认 2)保底。
    """
    floor = max(0.0, _env_float("SQH_DAILY_CLAUDE_USD", 2.0))
    share = max(0.0, min(100.0, _env_float("SQH_CLAUDE_SHARE_PCT", 30.0)))
    try:
        from ....services.ai_usage_ledger import claude_budget_overview

        overview = claude_budget_overview()
    except Exception:  # noqa: BLE001
        overview = None
    if not overview or overview.get("mode") != "dynamic":
        return floor
    return round(float(overview.get("total_allowance_today_usd") or 0) * share / 100, 2)


def loop_seconds() -> float:
    return max(5.0, _env_float("SQH_LOOP_SECONDS", 60.0))


# ---------------------------------------------------------------- 登录浏览器(10-28)

# fetch_offer 被拦但页面留在登录浏览器里等老板时,block_reason 以它开头(后面跟原始原因)
NEEDS_HUMAN = "needs_human:"



def browser_enabled() -> bool:
    """SQH_BROWSER=1:1688 走 worker 里常驻的登录浏览器(老板扫码登录一次,cookie 落在 profile 里跨重启);
    默认关,关着就还是每次新开匿名无头浏览器的老路。"""
    return os.getenv("SQH_BROWSER", "0").strip().lower() in ("1", "true", "yes", "on")


def browser_profile_dir() -> str:
    """Chromium 的 profile 放在 worker 已挂的 agent-memory 卷上。"""
    root = os.getenv("AGENT_MEMORY_DIR", "/var/lib/barong/agent-memory")
    return os.getenv("SQH_BROWSER_PROFILE_DIR", os.path.join(root, "suqinghe", "chrome-1688"))


def browser_dump_dir() -> str:
    root = os.getenv("AGENT_MEMORY_DIR", "/var/lib/barong/agent-memory")
    return os.getenv("SQH_BROWSER_DUMP_DIR", os.path.join(root, "suqinghe", "browser-dumps"))


def browser_idle_minutes() -> float:
    """没活多久就把浏览器关掉(profile 留着)。"""
    return max(1.0, _env_float("SQH_BROWSER_IDLE_MINUTES", 10.0))


def browser_hold_minutes() -> float:
    """等老板过验证最多等多久,超了档案转 blocked。"""
    return max(5.0, _env_float("SQH_BROWSER_HOLD_MINUTES", 120.0))


def seller_chat_enabled() -> bool:
    """SQH_SELLER_CHAT=1(B 期,10-29):详情页没有重量尺寸、或各规格同一个重量疑似乱填时,她用老板的 1688 账号去旺旺问卖家。默认关。"""
    return os.getenv("SQH_SELLER_CHAT", "0").strip().lower() in ("1", "true", "yes", "on")


def seller_chat_wait_hours() -> float:
    """问了卖家最多等多久;超了价格卡照旧出,写明「问了没回」。"""
    return max(1.0, _env_float("SQH_SELLER_CHAT_WAIT_HOURS", 24.0))


def seller_chat_poll_minutes() -> float:
    """问了之后隔多久去旺旺看一次回复。"""
    return max(5.0, _env_float("SQH_SELLER_CHAT_POLL_MINUTES", 15.0))


def gsc_site() -> str:
    """Search Console 的资源名(网域资源 sc-domain:…;网址前缀资源就是完整 URL)。"""
    return os.getenv("SQH_GSC_SITE", "sc-domain:barongyekhna.com").strip() or "sc-domain:barongyekhna.com"


def gsc_lag_days() -> int:
    """谷歌的搜索数据要 2–3 天才定稿,按 today-lag 拉。"""
    try:
        return max(1, int(os.getenv("SQH_GSC_LAG_DAYS", "3")))
    except ValueError:
        return 3


def gsc_backfill_days() -> int:
    try:
        return max(7, min(480, int(os.getenv("SQH_GSC_BACKFILL_DAYS", "90"))))
    except ValueError:
        return 90


def retry_after_block() -> bool:
    """被拦之后今天还继续抓不抓(默认不:「今天先不碰」)。"""
    return os.getenv("SQH_1688_RETRY_AFTER_BLOCK", "0").strip().lower() in ("1", "true", "yes", "on")
