"""R-A product-selection skill metadata loader.

The loader intentionally returns metadata and hashes only. Runtime prompt
assembly will use the same file registry later, but the framework endpoint does
not expose full prompt content.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any


DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"

SKILL_FILES: tuple[tuple[str, str, str], ...] = (
    ("skill", "核心判断手册", "SKILL.md"),
    ("amazon", "亚马逊 FBA 准则", "amazon.md"),
    ("dtc", "独立站 DTC 准则", "dtc.md"),
    ("dtc_data", "独立站数据源准则", "dtc_data.md"),
    ("shared", "双平台通用红线", "shared.md"),
    ("ra_supplier_keyword", "R-A 供应商关键词与变体匹配", "ra_supplier_keyword_skill.md"),
)

CHANNEL_FILE_KEYS: dict[str, tuple[str, ...]] = {
    "amazon": ("skill", "amazon", "shared"),
    "dtc_seo": ("skill", "dtc", "dtc_data", "shared"),
    "dtc_ad": ("skill", "dtc", "dtc_data", "shared"),
    "both": ("skill", "amazon", "dtc", "dtc_data", "shared"),
    "profit_supplier": ("skill", "amazon", "shared", "ra_supplier_keyword"),
}


@dataclass(frozen=True)
class RASkillFile:
    key: str
    label: str
    filename: str
    exists: bool
    sha256: str | None
    bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "filename": self.filename,
            "exists": self.exists,
            "sha256": self.sha256,
            "bytes": self.bytes,
        }


@dataclass(frozen=True)
class RASkillBundleFile:
    key: str
    label: str
    filename: str
    sha256: str
    bytes: int
    content: str

    def to_dict(self, *, include_content: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "key": self.key,
            "label": self.label,
            "filename": self.filename,
            "sha256": self.sha256,
            "bytes": self.bytes,
        }
        if include_content:
            payload["content"] = self.content
        return payload


@dataclass(frozen=True)
class RASkillBundle:
    channel: str
    name: str
    version: str
    description: str
    files: tuple[RASkillBundleFile, ...]
    combined_hash: str
    prompt_text: str

    def to_dict(self, *, include_content: bool = False) -> dict[str, object]:
        return {
            "channel": self.channel,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "files": [
                item.to_dict(include_content=include_content) for item in self.files
            ],
            "file_keys": [item.key for item in self.files],
            "combined_hash": self.combined_hash,
            "prompt_text": self.prompt_text if include_content else None,
        }


def load_ra_skill_manifest(docs_dir: Path = DOCS_DIR) -> dict[str, Any]:
    files = [_load_file_metadata(docs_dir, *item) for item in SKILL_FILES]
    metadata = _skill_frontmatter(docs_dir / "SKILL.md")
    loaded = all(item.exists for item in files)
    return {
        "loaded": loaded,
        "name": metadata.get("name", "product-selection"),
        "version": metadata.get("version", ""),
        "description": metadata.get("description", ""),
        "docs_dir": str(docs_dir),
        "files": [item.to_dict() for item in files],
        "channels": [
            {
                "channel": channel,
                "files": list(file_keys),
                "loaded": all(_file_by_key(files, key).exists for key in file_keys),
            }
            for channel, file_keys in CHANNEL_FILE_KEYS.items()
        ],
        "prompt_content_exposed": False,
    }


def load_ra_skill_bundle(channel: str, docs_dir: Path = DOCS_DIR) -> RASkillBundle:
    """Load the concrete skill documents used for an R-A analysis channel."""

    metadata = _skill_frontmatter(docs_dir / "SKILL.md")
    normalized_channel = _normalize_channel(channel)
    files_by_key = {
        key: (label, filename)
        for key, label, filename in SKILL_FILES
    }
    bundle_files: list[RASkillBundleFile] = []
    for key in skill_file_keys_for_channel(normalized_channel):
        label, filename = files_by_key[key]
        path = docs_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"R-A skill file missing: {filename}")
        content = path.read_text(encoding="utf-8")
        encoded = content.encode("utf-8")
        bundle_files.append(
            RASkillBundleFile(
                key=key,
                label=label,
                filename=filename,
                sha256=sha256(encoded).hexdigest(),
                bytes=len(encoded),
                content=content,
            )
        )
    combined_basis = "\n".join(
        f"{item.key}:{item.filename}:{item.sha256}" for item in bundle_files
    )
    prompt_text = "\n\n".join(
        [
            f"## R-A Skill Document: {item.label} ({item.filename})\n{item.content}"
            for item in bundle_files
        ]
    )
    return RASkillBundle(
        channel=normalized_channel,
        name=metadata.get("name", "product-selection"),
        version=metadata.get("version", ""),
        description=metadata.get("description", ""),
        files=tuple(bundle_files),
        combined_hash=sha256(combined_basis.encode("utf-8")).hexdigest(),
        prompt_text=prompt_text,
    )


def skill_file_keys_for_channel(channel: str) -> tuple[str, ...]:
    return CHANNEL_FILE_KEYS.get(_normalize_channel(channel), CHANNEL_FILE_KEYS["both"])


def _normalize_channel(channel: str) -> str:
    normalized = str(channel or "both").strip().lower().replace("-", "_")
    if normalized in CHANNEL_FILE_KEYS:
        return normalized
    return "both"


def _load_file_metadata(
    docs_dir: Path,
    key: str,
    label: str,
    filename: str,
) -> RASkillFile:
    path = docs_dir / filename
    if not path.is_file():
        return RASkillFile(
            key=key,
            label=label,
            filename=filename,
            exists=False,
            sha256=None,
            bytes=0,
        )
    content = path.read_bytes()
    return RASkillFile(
        key=key,
        label=label,
        filename=filename,
        exists=True,
        sha256=sha256(content).hexdigest(),
        bytes=len(content),
    )


def _file_by_key(files: list[RASkillFile], key: str) -> RASkillFile:
    for item in files:
        if item.key == key:
            return item
    return RASkillFile(
        key=key,
        label=key,
        filename="",
        exists=False,
        sha256=None,
        bytes=0,
    )


def _skill_frontmatter(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata
