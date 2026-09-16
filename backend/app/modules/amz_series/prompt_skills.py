"""员工技能手册加载器:每位员工一组 markdown,全文进提示词;sha256 进台账,改了手册就能对得上账。

质量来自手册,不来自模型(家规)。手册是从外部技能库(MIT)剥壳后的骨架 + 我们自己的数字,
见 docs/AMZ_SKILL_SOURCES.md。这里只读文件、拼文本、算指纹,不出网。
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from .constants import EMPLOYEE_A, EMPLOYEE_B, EMPLOYEE_C, EMPLOYEE_D, EMPLOYEES

SKILLS_DIR = Path(__file__).parent / "skills"
SKILLS_VERSION = "2026-09-16.1"

EMPLOYEE_SKILLS: dict[str, tuple[str, ...]] = {
    EMPLOYEE_A: ("a/listing-copy.md", "shared/pnl-and-inventory.md"),
    EMPLOYEE_B: ("b/listing-images.md",),
    EMPLOYEE_C: ("c/competitors-and-sqp.md", "shared/pnl-and-inventory.md"),
    EMPLOYEE_D: ("d/ads-funnel-and-bids.md", "shared/pnl-and-inventory.md"),
}
ALL_SKILL_FILES: tuple[str, ...] = tuple(sorted({path for paths in EMPLOYEE_SKILLS.values() for path in paths}))
REQUIRED_HEADER_MARKS = ("来源:", "MIT", "https://github.com/liangdabiao/Amazon-Skills-Liang")
MAX_CHARS_PER_EMPLOYEE = 14000


def skill_path(relative: str) -> Path:
    return SKILLS_DIR / relative


@lru_cache(maxsize=32)
def load_skill(relative: str) -> tuple[str, str]:
    """(全文, sha256)。"""
    text = skill_path(relative).read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def skills_for(employee: str) -> str:
    """拼给某位员工的手册文本(进 system 第二条)。"""
    employee = employee.upper()
    if employee not in EMPLOYEES:
        raise KeyError(employee)
    parts = []
    for relative in EMPLOYEE_SKILLS[employee]:
        text, _ = load_skill(relative)
        parts.append(text.strip())
    body = "\n\n---\n\n".join(parts)
    if len(body) > MAX_CHARS_PER_EMPLOYEE:
        body = body[:MAX_CHARS_PER_EMPLOYEE].rstrip() + "\n…(手册过长,后段截断)"
    return f"## 你的技能手册(版本 {SKILLS_VERSION};照着做,数字冲突时以你手上的真实数据和护栏为准)\n\n{body}"


def manifest() -> dict[str, dict[str, str]]:
    """每份手册的指纹,给台账 / 测试 / 将来的经验库版本比对用。"""
    out: dict[str, dict[str, str]] = {}
    for relative in ALL_SKILL_FILES:
        _, digest = load_skill(relative)
        out[relative] = {"sha256": digest, "version": SKILLS_VERSION}
    return out


__all__ = ["ALL_SKILL_FILES", "EMPLOYEE_SKILLS", "MAX_CHARS_PER_EMPLOYEE", "REQUIRED_HEADER_MARKS", "SKILLS_DIR", "SKILLS_VERSION", "load_skill", "manifest", "skills_for"]
