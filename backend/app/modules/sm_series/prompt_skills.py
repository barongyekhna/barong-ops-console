"""社媒写手的 skill 加载与提示词拼装。

质量来自 skill，不来自模型（家规）。SKILL.md 全文进提示词，sha256 进
skill context——skill 一改，下游指纹就变。加载器照 K 的 ``_load_skill_markdown``
（四行），目录指向本模块，不去改 K。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..content_core.writing_rules import ARITHMETIC_EN
from .constants import FORBIDDEN_PHRASES, SM_POST_SKILL_VERSION
from .profiles import PlatformProfile

_SKILLS_DIR = Path(__file__).parent / "skills"
_SKILL_FOLDER = "social-image-post-playbook"


def load_skill_markdown(folder: str = _SKILL_FOLDER, filename: str = "SKILL.md") -> tuple[str, str]:
    """(markdown_body, sha256)。"""
    text = (_SKILLS_DIR / folder / filename).read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def skill_context() -> dict[str, Any]:
    body, digest = load_skill_markdown()
    return {
        "version": SM_POST_SKILL_VERSION,
        "name": _SKILL_FOLDER,
        "content_sha256": digest,
        "skill_markdown": body,
    }


_SECTION_RE = re.compile(r"^## ", re.M)


def skill_sections(body: str) -> dict[str, str]:
    """按二级标题切成段，键是标题里的 § 编号或全文标题；写手只塞需要的段。"""
    parts = _SECTION_RE.split(body)
    out: dict[str, str] = {}
    for part in parts[1:]:
        title, _, rest = part.partition("\n")
        match = re.match(r"§(\d+)", title.strip())
        key = f"§{match.group(1)}" if match else title.strip()
        out[key] = "## " + part
    return out


# 输出 JSON 契约（skill §8）。写在代码里而不是只在 markdown 里，因为解析器按它读。
OUTPUT_KEYS: tuple[str, ...] = (
    "platform",
    "pillar",
    "title",
    "caption",
    "first_line",
    "alt_text",
    "hashtags",
    "board",
    "cta",
    "keyword_primary",
    "keywords_secondary",
    "facts_used",
    "overlay_texts",
    "derived_numbers",
    "blocked_reason",
)


def build_messages(
    *,
    skill_markdown: str,
    profile: PlatformProfile,
    pillar: str,
    post_kind: str,
    source_snapshot: dict[str, Any],
    media_plan: list[dict[str, Any]],
    keyword_hints: dict[str, Any],
    critique: list[str] | None = None,
    previous_output: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """system = skill 全文 + 平台档案 + 输出契约；user = 源头快照 + 这一格的任务。"""
    sections = skill_sections(skill_markdown)
    # §5「示例」刻意不进提示词：示例里有具体产品的占位文案，喂给模型就会被
    # 当成本次产品来复述（B2B 提示词写死产品名的事故同型，derive-don't-ask）。
    # 示例是给人读的；模型看规则 + 本次源头快照就够了。
    platform_rules = sections.get("§3", "") + sections.get("§4", "")
    house_rules = sections.get("§0", "")
    pillars = sections.get("§2", "")
    redlines = sections.get("§7", "")

    system = (
        "You are the social-media copywriter for the DTC brand Barong Yekhna. "
        "You write ONE image post for ONE platform. Follow the SKILL below to the letter; "
        "the platform profile JSON is a hard constraint; the output must be a single JSON object.\n\n"
        "=== SKILL (house rules first) ===\n"
        f"{house_rules}\n{pillars}\n{platform_rules}\n{redlines}\n"
        "=== PLATFORM PROFILE (hard constraints) ===\n"
        f"{json.dumps(profile.to_dict(), ensure_ascii=False)}\n\n"
        "=== FACT RULES ===\n"
        "Every number, certification, delivery time and return claim MUST come from the "
        "source snapshot below. List every fact you used in `facts_used` as dotted paths "
        "into the snapshot (e.g. `k.structured_specs_json.flow_gpm`, `craft_facts.<id>`, "
        "`geo.sections[2]`). A post whose text contains a number that is not in the snapshot "
        "is rejected by the server. If the snapshot is too thin to write this pillar honestly, "
        "return `blocked_reason` and leave the copy fields empty.\n"
        f"{ARITHMETIC_EN}"
        "Never mention these phrases (business-identity house rule): "
        + ", ".join(FORBIDDEN_PHRASES)
        + ". Sold by Guangzhou Longjie E-Commerce; made in our own factory in Jilin; "
        "team in Los Angeles. Imperial units for US buyers.\n\n"
        "=== OUTPUT (JSON only, no prose) ===\n"
        "{"
        + ", ".join(f'"{key}": ...' for key in OUTPUT_KEYS)
        + "}\n"
        "`hashtags` is a list (empty for Pinterest, max 5 for Instagram, lowercase, no '#'). "
        "`overlay_texts` is a list of ≤8-word headlines, one per image slot that allows overlay, "
        "else []. `derived_numbers` follows the ARITHMETIC rule. `keywords_secondary` is a list."
    )

    task = {
        "platform": profile.platform,
        "pillar": pillar,
        "post_kind": post_kind,
        "keyword_hints": keyword_hints,
        "media_plan": media_plan,
        "source": source_snapshot,
    }
    if critique:
        task["critique_to_address"] = critique
    if previous_output:
        task["previous_output"] = previous_output
        task["instruction"] = (
            "Rewrite the previous output so every critique above is addressed. Do not invent "
            "facts to satisfy a critique: if a critique needs data that is not in the source, "
            "list it under `blocked_reason` instead."
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(task, ensure_ascii=False, default=str)},
    ]


__all__ = [
    "OUTPUT_KEYS",
    "build_messages",
    "load_skill_markdown",
    "skill_context",
    "skill_sections",
]
