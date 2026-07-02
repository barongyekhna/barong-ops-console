"""Skill metadata loader for R-W UI and worker status."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = REPO_ROOT / "r_system_v2" / "docs" / "SKILL.md"


def load_deepseek_skill_metadata(path: Path = SKILL_PATH) -> dict[str, str | bool]:
    if not path.exists():
        return {
            "installed": False,
            "name": "product-selection",
            "version": "unknown",
            "label": "DeepSeek 初筛 Skill 未安装",
            "path": str(path),
        }

    text = path.read_text(encoding="utf-8")
    version = "v1"
    name = "product-selection"
    in_frontmatter = text.startswith("---")
    if in_frontmatter:
        for line in text.splitlines()[1:]:
            if line.strip() == "---":
                break
            key, separator, value = line.partition(":")
            if separator != ":":
                continue
            if key.strip() == "version" and value.strip():
                version = value.strip()
            if key.strip() == "name" and value.strip():
                name = value.strip()

    installed = "DeepSeek" in text and "量化过滤器" in text
    return {
        "installed": installed,
        "name": name,
        "version": version,
        "label": f"已安装 DeepSeek 初筛 Skill {version}" if installed else "DeepSeek 初筛 Skill 未安装",
        "path": str(path),
    }
