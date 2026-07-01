"""R System v2 memory-only loader.

This module builds an in-process runtime memory context from the design docs.
It does not create databases, start workers, call external APIs, or invoke AI.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


R_SYSTEM_ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = R_SYSTEM_ROOT / "core"
DOCS_DIR = R_SYSTEM_ROOT / "docs"
MEMORY_FILE = CORE_DIR / "memory.json"

DOC_FILES = (
    "ARCHITECTURE.md",
    "SKILL.md",
    "shared.md",
    "amazon.md",
    "dtc.md",
    "dtc_data.md",
    "README.md",
)
ZIP_FILES = ("product-selection.zip",)
RULE_SOURCES = {
    "amazon_rules": "amazon.md",
    "dtc_rules": "dtc.md",
    "shared_rules": "shared.md",
}

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class RuntimeMemoryContext:
    """Structured, in-memory representation of R System v2 design memory."""

    static_memory: dict[str, Any]
    documents: dict[str, Any]
    rules: dict[str, Any]
    knowledge_packages: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "system_type": self.static_memory["system_type"],
            "system_status": self.static_memory["system_status"],
            "runtime_initialized": False,
            "business_logic_executed": False,
            "static_memory": self.static_memory,
            "documents": self.documents,
            "rules": self.rules,
            "knowledge_packages": self.knowledge_packages,
        }


RUNTIME_CONTEXT: dict[str, Any] = {
    "system_type": "R_SYSTEM_V2",
    "memory_loaded": False,
    "runtime_initialized": False,
    "business_logic_executed": False,
    "memory": None,
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8") as handle:
        return handle.read()


def _parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}

    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def _parse_markdown(name: str, text: str) -> dict[str, Any]:
    headings = []
    non_empty_lines = 0

    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            non_empty_lines += 1

        heading = HEADING_RE.match(line)
        if heading:
            headings.append(
                {
                    "level": len(heading.group(1)),
                    "title": heading.group(2).strip(),
                    "line": line_number,
                }
            )

    return {
        "name": name,
        "frontmatter": _parse_frontmatter(text),
        "outline": headings,
        "stats": {
            "chars": len(text),
            "lines": len(text.splitlines()),
            "non_empty_lines": non_empty_lines,
        },
        "content": text,
    }


def _read_zip_manifest(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as package:
        entries = [
            {
                "name": info.filename,
                "size": info.file_size,
                "is_dir": info.is_dir(),
            }
            for info in package.infolist()
        ]

    return {
        "name": path.name,
        "path": str(path),
        "entries": entries,
        "entry_count": len(entries),
    }


def build_runtime_memory(
    docs_dir: Path = DOCS_DIR,
    memory_file: Path = MEMORY_FILE,
) -> RuntimeMemoryContext:
    """Read design files and build structured memory without side effects."""

    static_memory = _read_json(memory_file)

    documents = {
        file_name: _parse_markdown(file_name, _read_text(docs_dir / file_name))
        for file_name in DOC_FILES
    }

    rules = {
        rule_name: {
            "source": source_file,
            "document": documents[source_file],
        }
        for rule_name, source_file in RULE_SOURCES.items()
    }

    knowledge_packages = {
        file_name: _read_zip_manifest(docs_dir / file_name)
        for file_name in ZIP_FILES
    }

    return RuntimeMemoryContext(
        static_memory=static_memory,
        documents=documents,
        rules=rules,
        knowledge_packages=knowledge_packages,
    )


def load_runtime_context() -> dict[str, Any]:
    """Load R System v2 design memory into the module-level runtime context."""

    memory = build_runtime_memory().as_dict()
    RUNTIME_CONTEXT.update(
        {
            "memory_loaded": True,
            "runtime_initialized": False,
            "business_logic_executed": False,
            "memory": memory,
        }
    )
    return RUNTIME_CONTEXT
