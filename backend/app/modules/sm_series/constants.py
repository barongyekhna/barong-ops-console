"""SM 系列固定常量。改这里的值 = 改门禁，走版本号。"""

from __future__ import annotations

MODULE_KEY = "sm.social"

PERMISSION_READ = "sm.social.read"
PERMISSION_EXECUTE = "sm.social.execute"
PERMISSION_MANAGE = "sm.social.manage"
PERMISSION_KEYS: tuple[str, ...] = (
    PERMISSION_READ,
    PERMISSION_EXECUTE,
    PERMISSION_MANAGE,
)

# 三个图文平台。视频类（tiktok / youtube）等视频线，不在本期常量里。
PLATFORM_PINTEREST = "pinterest"
PLATFORM_INSTAGRAM = "instagram"
PLATFORM_FACEBOOK = "facebook"
PLATFORMS: tuple[str, ...] = (PLATFORM_PINTEREST, PLATFORM_INSTAGRAM, PLATFORM_FACEBOOK)

# 五根内容支柱（skill §2）。
PILLAR_PRODUCT = "P1"
PILLAR_GUIDE = "P2"
PILLAR_FACTORY = "P3"
PILLAR_SCENE = "P4"
PILLAR_BRAND = "P5"
PILLARS: tuple[str, ...] = (
    PILLAR_PRODUCT,
    PILLAR_GUIDE,
    PILLAR_FACTORY,
    PILLAR_SCENE,
    PILLAR_BRAND,
)
PILLAR_LABELS: dict[str, str] = {
    PILLAR_PRODUCT: "产品",
    PILLAR_GUIDE: "导购",
    PILLAR_FACTORY: "工厂",
    PILLAR_SCENE: "场景",
    PILLAR_BRAND: "品牌",
}
# 工厂 / 品牌是「信任的标点」：永远不连着两天出现（skill 排期规则 1）。
PUNCTUATION_PILLARS: frozenset[str] = frozenset({PILLAR_FACTORY, PILLAR_BRAND})

SOURCE_K_PRODUCT = "k_product"
SOURCE_GEO_ITEM = "geo_item"
SOURCE_CRAFT_FACT = "craft_fact"
SOURCE_MANUAL = "manual"
SOURCE_NONE = "none"
SOURCE_TYPES: tuple[str, ...] = (
    SOURCE_K_PRODUCT,
    SOURCE_GEO_ITEM,
    SOURCE_CRAFT_FACT,
    SOURCE_MANUAL,
    SOURCE_NONE,
)

POST_KIND_PIN = "pinterest_pin"
POST_KIND_CAROUSEL = "instagram_carousel"
POST_KIND_SINGLE = "instagram_single"
POST_KIND_MIRROR = "facebook_mirror"
POST_KINDS: tuple[str, ...] = (POST_KIND_PIN, POST_KIND_CAROUSEL, POST_KIND_SINGLE, POST_KIND_MIRROR)
POST_KIND_LABELS: dict[str, str] = {
    POST_KIND_PIN: "Pinterest 图钉",
    POST_KIND_CAROUSEL: "Instagram 轮播",
    POST_KIND_SINGLE: "Instagram 单图",
    POST_KIND_MIRROR: "Facebook 镜像",
}

# 缺口单三条道（报告 03.7）。
LANE_LAYOUT = "layout"
LANE_MCP = "mcp"
LANE_PHOTO = "photo"
LANES: tuple[str, ...] = (LANE_LAYOUT, LANE_MCP, LANE_PHOTO)

# K 媒体资产角色：SM 只读 K 的角色，只新增两个自己的。
ASSET_ROLE_MAIN = "main"
ASSET_ROLE_GALLERY = "gallery"
ASSET_ROLE_DESCRIPTION = "description"
ASSET_ROLE_FACTORY = "factory"
ASSET_ROLE_BRAND = "brand"
ASSET_ROLE_SOCIAL_LAYOUT = "social_layout"
# 版式渲染产物的血统标记（metadata.render_pipeline）。K 的 list_render_assets
# 只认 k_auto_render，所以 SM 的版式图不会混进 K 的渲染面板。
LAYOUT_PIPELINE_TAG = "sm_layout"
REAL_PHOTO_ROLES: frozenset[str] = frozenset({ASSET_ROLE_FACTORY})

# 驳回原因（报告 03.8，六种各配动作）。
REJECT_WRONG_VARIANT = "wrong_variant"
REJECT_BAD_LAYOUT = "bad_layout"
REJECT_WRONG_SCENE = "wrong_scene"
REJECT_AI_ARTIFACT = "ai_artifact"
REJECT_BRAND = "brand_violation"
REJECT_TASTE = "taste"
REJECT_REASONS: tuple[str, ...] = (
    REJECT_WRONG_VARIANT,
    REJECT_BAD_LAYOUT,
    REJECT_WRONG_SCENE,
    REJECT_AI_ARTIFACT,
    REJECT_BRAND,
    REJECT_TASTE,
)
REJECT_REASON_LABELS: dict[str, str] = {
    REJECT_WRONG_VARIANT: "产品或变体色不对",
    REJECT_BAD_LAYOUT: "裁得不好 / 叠字挡产品",
    REJECT_WRONG_SCENE: "场景不对",
    REJECT_AI_ARTIFACT: "AI 痕迹 / 变形",
    REJECT_BRAND: "违反品牌门 / 口径",
    REJECT_TASTE: "就是不好看",
}

SM_POST_SKILL_VERSION = "sm-image-post-playbook-v1"
PLANNER_VERSION = "sm-planner-v1"
PROFILE_VERSION = "sm-profiles-v1"

WORKER_NAME = "sm-worker"
# 心跳预期间隔：worker 每轮至少做一件事（排日历 / 写帖 / 扫缺口）。
WORKER_HEARTBEAT_INTERVAL_SECONDS = 900

# 排期窗口与冷却（skill 排期规则）。
PLAN_HORIZON_DAYS = 28
SAME_SOURCE_COOLDOWN_DAYS = 7
SEEDING_PERIOD_DAYS = 14
GAP_SWAP_LEAD_DAYS = 2
GAP_DORMANT_AFTER_DAYS = 30
NO_SOURCE_STUCK_DAYS = 14
# 每平台每源图最多几个版式变体（Pinterest 近重复降权）。
MAX_LAYOUT_VARIANTS_PER_SOURCE = 3

# 社媒位号段：K 简报里 1..N 是作图指令，101+ 是变体色主图，201+ 归 SM。
SOCIAL_POSITION_BASE = 200

# 口径黑名单：三家主体口径全站一致（家规 §0）。出现即品牌门违规。
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "shenzhen",
    "深圳",
    "guangzhou factory",
    "factory in guangzhou",
    "facility in guangzhou",
    "assembly floor is in guangzhou",
    "leading manufacturer",
)

__all__ = [name for name in dir() if name.isupper()]
