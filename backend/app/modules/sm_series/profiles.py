"""渠道档案（报告 03.6）：一平台一行，排期器是一台引擎读几行服务几个平台。

**为什么是代码常量不是表**：档案是硬约束——voice、标签上限、链接位置改了
就是换平台玩法，得走版本号；指标只准在 pillar_mix 上下 10 个点内微调
（本期没有指标，配比就是这里写的）。表适合会被人天天改的东西，这不是。

来源与核实日期见 skills/social-image-post-playbook/SKILL.md 文末。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import (
    ASSET_ROLE_BRAND,
    ASSET_ROLE_DESCRIPTION,
    ASSET_ROLE_FACTORY,
    ASSET_ROLE_GALLERY,
    ASSET_ROLE_MAIN,
    PILLAR_BRAND,
    PILLAR_FACTORY,
    PILLAR_GUIDE,
    PILLAR_PRODUCT,
    PILLAR_SCENE,
    PLATFORM_FACEBOOK,
    PLATFORM_INSTAGRAM,
    PLATFORM_PINTEREST,
    POST_KIND_CAROUSEL,
    POST_KIND_MIRROR,
    POST_KIND_PIN,
    POST_KIND_SINGLE,
    PROFILE_VERSION,
)


@dataclass(frozen=True)
class PlatformProfile:
    platform: str
    voice: str  # utility | friend | mirror_of:<platform>
    pillar_mix: dict[str, int]  # 百分比，和为 100
    # 每周固定节拍：weekday(0=周一) → 支柱；Pinterest 用 per_day 而不是周模板。
    weekly_template: dict[int, str]
    per_day: tuple[int, int]  # Pinterest 每天钉数上下限；其它平台 (0,0)
    windows_pt: tuple[str, ...]  # 太平洋时间发布时段
    formats: tuple[str, ...]
    image_ratio: str
    image_min_px: tuple[int, int]
    overlay_max_area: float
    title_max: int
    title_visible: int
    caption_max: int
    first_line_max: int
    alt_max: int
    hashtags_max: int
    link_mode: str  # in_post | bio_only | first_comment
    cooldown_days_same_source: int
    seeding_days: int
    skill_section: str
    version: str = PROFILE_VERSION
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "voice": self.voice,
            "pillar_mix": dict(self.pillar_mix),
            "weekly_template": {str(k): v for k, v in self.weekly_template.items()},
            "per_day": list(self.per_day),
            "windows_pt": list(self.windows_pt),
            "formats": list(self.formats),
            "image": {
                "ratio": self.image_ratio,
                "min_px": list(self.image_min_px),
                "overlay_max_area": self.overlay_max_area,
            },
            "fields": {
                "title": self.title_max,
                "title_visible": self.title_visible,
                "caption": self.caption_max,
                "first_line": self.first_line_max,
                "alt": self.alt_max,
            },
            "hashtags": {"max": self.hashtags_max},
            "link": {"mode": self.link_mode, "utm": True},
            "cooldown_days_same_source": self.cooldown_days_same_source,
            "phase_rules": {"seeding_days": self.seeding_days},
            "skill_section": self.skill_section,
            "version": self.version,
            "notes": self.notes,
        }


PLATFORM_PROFILES: dict[str, PlatformProfile] = {
    PLATFORM_PINTEREST: PlatformProfile(
        platform=PLATFORM_PINTEREST,
        voice="utility",
        pillar_mix={PILLAR_GUIDE: 40, PILLAR_PRODUCT: 30, PILLAR_SCENE: 20, PILLAR_FACTORY: 10, PILLAR_BRAND: 0},
        # Pinterest 不按周模板：每天混发，工厂钉只在周末（planner 里处理）。
        weekly_template={},
        per_day=(3, 5),
        windows_pt=("07:30", "12:00", "20:00"),
        formats=(POST_KIND_PIN,),
        image_ratio="2:3",
        image_min_px=(1000, 1500),
        overlay_max_area=0.30,
        title_max=100,
        title_visible=40,
        caption_max=500,
        first_line_max=0,
        alt_max=125,
        hashtags_max=0,
        link_mode="in_post",
        cooldown_days_same_source=7,
        seeding_days=14,
        skill_section="pinterest",
        notes="搜索引擎 + 工具书。关键词进标题前 40 字符，标签无效。",
    ),
    PLATFORM_INSTAGRAM: PlatformProfile(
        platform=PLATFORM_INSTAGRAM,
        voice="friend",
        pillar_mix={PILLAR_GUIDE: 35, PILLAR_SCENE: 25, PILLAR_FACTORY: 20, PILLAR_PRODUCT: 15, PILLAR_BRAND: 5},
        # 周一导购轮播 / 周二产品轮播 / 周四场景单图 / 周六工厂（或品牌，planner 按月配额替换）
        weekly_template={0: PILLAR_GUIDE, 1: PILLAR_PRODUCT, 3: PILLAR_SCENE, 5: PILLAR_FACTORY},
        per_day=(0, 0),
        windows_pt=("08:30",),
        formats=(POST_KIND_CAROUSEL, POST_KIND_SINGLE),
        image_ratio="4:5",
        image_min_px=(1080, 1350),
        overlay_max_area=0.30,
        title_max=0,
        title_visible=0,
        caption_max=2200,
        first_line_max=125,
        alt_max=125,
        hashtags_max=5,
        link_mode="bio_only",
        cooldown_days_same_source=7,
        seeding_days=14,
        skill_section="instagram",
        notes="杂志 + 朋友的相册。收藏与转发压过点赞；标签 ≤5；前 125 字符即全部。",
    ),
    PLATFORM_FACEBOOK: PlatformProfile(
        platform=PLATFORM_FACEBOOK,
        voice=f"mirror_of:{PLATFORM_INSTAGRAM}",
        pillar_mix={PILLAR_GUIDE: 35, PILLAR_SCENE: 25, PILLAR_FACTORY: 20, PILLAR_PRODUCT: 15, PILLAR_BRAND: 5},
        # 一三五镜像 Instagram 最近一条（planner 里取镜像源，不独立排支柱）
        weekly_template={0: "mirror", 2: "mirror", 4: "mirror"},
        per_day=(0, 0),
        windows_pt=("09:00",),
        formats=(POST_KIND_MIRROR,),
        image_ratio="4:5",
        image_min_px=(1080, 1350),
        overlay_max_area=0.30,
        title_max=0,
        title_visible=0,
        caption_max=2200,
        first_line_max=125,
        alt_max=125,
        hashtags_max=3,
        link_mode="first_comment",
        cooldown_days_same_source=7,
        seeding_days=14,
        skill_section="facebook",
        notes="社区公告板。镜像 Instagram，正文不带链接，链接进第一条评论。",
    ),
}


def profile(platform: str) -> PlatformProfile:
    try:
        return PLATFORM_PROFILES[platform]
    except KeyError as exc:  # pragma: no cover - 调用方先校验
        raise ValueError(f"未知平台：{platform!r}") from exc


@dataclass(frozen=True)
class ImageRequirement:
    """一个「支柱 × 平台」要什么图（报告 03.7 第一步）。"""

    roles: tuple[str, ...]
    ratio: str
    count_min: int
    count_max: int
    overlay: bool
    must_be_real: bool
    # 没有源图时能不能用纯字卡（版式道）顶上。
    text_card_ok: bool = False
    post_kind: str = POST_KIND_PIN
    extra: dict[str, Any] = field(default_factory=dict)


IMAGE_REQUIREMENTS: dict[tuple[str, str], ImageRequirement] = {
    (PILLAR_PRODUCT, PLATFORM_PINTEREST): ImageRequirement(
        roles=(ASSET_ROLE_MAIN, ASSET_ROLE_GALLERY), ratio="2:3", count_min=1, count_max=1,
        overlay=False, must_be_real=False, post_kind=POST_KIND_PIN,
    ),
    (PILLAR_PRODUCT, PLATFORM_INSTAGRAM): ImageRequirement(
        roles=(ASSET_ROLE_MAIN, ASSET_ROLE_GALLERY), ratio="4:5", count_min=4, count_max=6,
        overlay=True, must_be_real=False, post_kind=POST_KIND_CAROUSEL,
    ),
    (PILLAR_GUIDE, PLATFORM_PINTEREST): ImageRequirement(
        roles=(ASSET_ROLE_DESCRIPTION,), ratio="2:3", count_min=1, count_max=1,
        overlay=True, must_be_real=False, text_card_ok=True, post_kind=POST_KIND_PIN,
    ),
    (PILLAR_GUIDE, PLATFORM_INSTAGRAM): ImageRequirement(
        roles=(ASSET_ROLE_DESCRIPTION, ASSET_ROLE_GALLERY), ratio="4:5", count_min=5, count_max=7,
        overlay=True, must_be_real=False, text_card_ok=True, post_kind=POST_KIND_CAROUSEL,
    ),
    (PILLAR_SCENE, PLATFORM_PINTEREST): ImageRequirement(
        roles=(ASSET_ROLE_DESCRIPTION,), ratio="2:3", count_min=1, count_max=1,
        overlay=False, must_be_real=False, post_kind=POST_KIND_PIN,
    ),
    (PILLAR_SCENE, PLATFORM_INSTAGRAM): ImageRequirement(
        roles=(ASSET_ROLE_DESCRIPTION,), ratio="4:5", count_min=1, count_max=2,
        overlay=False, must_be_real=False, post_kind=POST_KIND_SINGLE,
    ),
    (PILLAR_FACTORY, PLATFORM_PINTEREST): ImageRequirement(
        roles=(ASSET_ROLE_FACTORY,), ratio="2:3", count_min=1, count_max=1,
        overlay=False, must_be_real=True, text_card_ok=True, post_kind=POST_KIND_PIN,
    ),
    (PILLAR_FACTORY, PLATFORM_INSTAGRAM): ImageRequirement(
        roles=(ASSET_ROLE_FACTORY,), ratio="4:5", count_min=1, count_max=3,
        overlay=False, must_be_real=True, text_card_ok=True, post_kind=POST_KIND_SINGLE,
    ),
    (PILLAR_BRAND, PLATFORM_INSTAGRAM): ImageRequirement(
        roles=(ASSET_ROLE_BRAND,), ratio="4:5", count_min=1, count_max=1,
        overlay=False, must_be_real=False, post_kind=POST_KIND_SINGLE,
    ),
}


def image_requirement(pillar: str, platform: str) -> ImageRequirement | None:
    """Facebook 是镜像，没有自己的需求单：拿 Instagram 的。"""
    if platform == PLATFORM_FACEBOOK:
        platform = PLATFORM_INSTAGRAM
    return IMAGE_REQUIREMENTS.get((pillar, platform))


def image_requirements_view() -> list[dict[str, Any]]:
    out = []
    for (pillar, platform), req in IMAGE_REQUIREMENTS.items():
        out.append(
            {
                "pillar": pillar,
                "platform": platform,
                "roles": list(req.roles),
                "ratio": req.ratio,
                "count_min": req.count_min,
                "count_max": req.count_max,
                "overlay": req.overlay,
                "must_be_real": req.must_be_real,
                "text_card_ok": req.text_card_ok,
                "post_kind": req.post_kind,
            }
        )
    return out


def validate_profiles() -> list[str]:
    """档案自检：配比和为 100、Pinterest 标签为 0、IG ≤5。测试钉住。"""
    problems: list[str] = []
    for key, prof in PLATFORM_PROFILES.items():
        if sum(prof.pillar_mix.values()) != 100:
            problems.append(f"{key}: pillar_mix 之和不是 100")
        if key == PLATFORM_PINTEREST and prof.hashtags_max != 0:
            problems.append("pinterest: 标签必须为 0")
        if key == PLATFORM_INSTAGRAM and prof.hashtags_max > 5:
            problems.append("instagram: 标签上限不能超过 5（2025-12 官方）")
        if prof.link_mode not in {"in_post", "bio_only", "first_comment"}:
            problems.append(f"{key}: 未知 link_mode")
    return problems


__all__ = [
    "IMAGE_REQUIREMENTS",
    "ImageRequirement",
    "PLATFORM_PROFILES",
    "PlatformProfile",
    "image_requirement",
    "image_requirements_view",
    "profile",
    "validate_profiles",
]
