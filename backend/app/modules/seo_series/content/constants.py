"""SEO 内容引擎的常量。

**分工的一句话版本**:GEO 写"这台机器怎么样"(接地在产品规格 → 卡产品数量),
SEO 写"我们怎么做出来的 / 批发怎么合作 / 这个品类该怎么挑"(接地在工艺事实、
店型、类目 → 不卡产品数量)。
"""

from __future__ import annotations

DEFAULT_WORKSPACE_KEY = "default_independent_store"
DEFAULT_BUSINESS_CONTEXT = "independent_store"
DEFAULT_SCOPE_MODE = "adapter_pending"

MODULE_KEY = "seo.content"
PERMISSION_READ = "seo.content.read"
PERMISSION_EXECUTE = "seo.content.execute"
PERMISSION_MANAGE = "seo.content.manage"

# 选题从哪来。
SOURCE_KEYWORD_RADAR = "keyword_radar"  # 关键词雷达
SOURCE_STORE_TYPE = "store_type"  # B 端店型覆盖
SOURCE_CRAFT_TOPIC = "craft_topic"  # 工艺库自己的话题
SOURCE_MANUAL = "manual"
TOPIC_SOURCES = (
    SOURCE_KEYWORD_RADAR,
    SOURCE_STORE_TYPE,
    SOURCE_CRAFT_TOPIC,
    SOURCE_MANUAL,
)

# 写给谁看。决定语气、CTA 指向、以及落哪个内容区。
AUDIENCE_CONSUMER = "consumer"  # C 端买家
AUDIENCE_WHOLESALE = "wholesale"  # B 端采购
AUDIENCE_BRAND = "brand"  # 品牌/公司/工厂信任
AUDIENCES = (AUDIENCE_CONSUMER, AUDIENCE_WHOLESALE, AUDIENCE_BRAND)

# 落在站上哪儿。三区各就各位,互不侵占:
#   /guides/  = GEO 的买家问句指南(不归 SEO 管)
#   /factory/ = 工艺 / 制造 / 品牌 / B 端采购(信任枢纽)
#   /posts/   = 纯 SEO 博文(GEO 够不到的 C 端话题)
DESTINATION_FACTORY = "factory"
DESTINATION_POSTS = "posts"
DESTINATIONS = (DESTINATION_FACTORY, DESTINATION_POSTS)

_DESTINATION_BY_AUDIENCE = {
    AUDIENCE_BRAND: DESTINATION_FACTORY,
    AUDIENCE_WHOLESALE: DESTINATION_FACTORY,
    AUDIENCE_CONSUMER: DESTINATION_POSTS,
}


def destination_for(audience: str) -> str:
    """落地区由受众推导——不问用户,也不让模型选。

    死规矩(2026-07-29 用户反馈「数据能推出来的判断系统自己算」):
    B 端采购和品牌工艺都是"证明我们是谁",归信任枢纽 /factory/;
    C 端话题是"帮你挑东西",归 /posts/。
    """
    return _DESTINATION_BY_AUDIENCE.get(audience, DESTINATION_POSTS)


# 文章体裁。每种对应一套结构,不是随便贴的标签。
ITEM_CRAFT_STORY = "craft_story"  # 一道工艺怎么做、为什么这么做
ITEM_MATERIAL_EXPLAINER = "material_explainer"  # 材料/元器件的取舍
ITEM_TESTING = "testing"  # 我们怎么测的、测出什么
ITEM_BUYING_GUIDE = "buying_guide"  # 品类怎么挑(C 端,GEO 够不到的上位话题)
ITEM_WHOLESALE_GUIDE = "wholesale_guide"  # B 端采购决策(MOQ/私标/交期/验厂/付款)
ITEM_BRAND_STORY = "brand_story"  # 公司/工厂/我们是谁
ITEM_KINDS = (
    ITEM_CRAFT_STORY,
    ITEM_MATERIAL_EXPLAINER,
    ITEM_TESTING,
    ITEM_BUYING_GUIDE,
    ITEM_WHOLESALE_GUIDE,
    ITEM_BRAND_STORY,
)

_KIND_BY_AUDIENCE = {
    AUDIENCE_BRAND: (
        ITEM_CRAFT_STORY,
        ITEM_MATERIAL_EXPLAINER,
        ITEM_TESTING,
        ITEM_BRAND_STORY,
    ),
    AUDIENCE_WHOLESALE: (ITEM_WHOLESALE_GUIDE,),
    AUDIENCE_CONSUMER: (ITEM_BUYING_GUIDE,),
}


def kinds_for(audience: str) -> tuple[str, ...]:
    return _KIND_BY_AUDIENCE.get(audience, (ITEM_BUYING_GUIDE,))


TOPIC_STATUSES = ("candidate", "picked", "rejected", "written")
REVIEW_STATUSES = ("pending", "approved", "rejected")
GENERATION_STATUSES = ("queued", "running", "generated", "failed")
JOB_STATUSES = ("queued", "running", "success", "failed")

# 雷达一次最多打多少个种子词。Keyword Planner 每次调用记 1 笔台账,
# 桶是 google_ads_planner(13500/天,与 R-A 共用)。
SEO_PUBLISH_PACKAGE_VERSION = "seo-publish-package-v1"

RADAR_MAX_SEEDS = 25
RADAR_IDEAS_PER_SEED = 10

__all__ = [
    "AUDIENCES",
    "AUDIENCE_BRAND",
    "AUDIENCE_CONSUMER",
    "AUDIENCE_WHOLESALE",
    "DEFAULT_BUSINESS_CONTEXT",
    "DEFAULT_SCOPE_MODE",
    "DEFAULT_WORKSPACE_KEY",
    "DESTINATIONS",
    "DESTINATION_FACTORY",
    "DESTINATION_POSTS",
    "GENERATION_STATUSES",
    "ITEM_BRAND_STORY",
    "ITEM_BUYING_GUIDE",
    "ITEM_CRAFT_STORY",
    "ITEM_KINDS",
    "ITEM_MATERIAL_EXPLAINER",
    "ITEM_TESTING",
    "ITEM_WHOLESALE_GUIDE",
    "JOB_STATUSES",
    "MODULE_KEY",
    "PERMISSION_EXECUTE",
    "PERMISSION_MANAGE",
    "PERMISSION_READ",
    "RADAR_IDEAS_PER_SEED",
    "SEO_PUBLISH_PACKAGE_VERSION",
    "RADAR_MAX_SEEDS",
    "REVIEW_STATUSES",
    "SOURCE_CRAFT_TOPIC",
    "SOURCE_KEYWORD_RADAR",
    "SOURCE_MANUAL",
    "SOURCE_STORE_TYPE",
    "TOPIC_SOURCES",
    "TOPIC_STATUSES",
    "destination_for",
    "kinds_for",
]
