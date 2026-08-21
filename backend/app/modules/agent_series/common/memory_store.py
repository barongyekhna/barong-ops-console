"""数字员工的记忆文件夹(参数化版):{AGENT_MEMORY_DIR}/{username}/。

一事一文件 + MEMORY.md 索引 + conversations/{user_id}.md 每人隔离 + state/ 机器状态。
老板随时能开、改、删。
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ....services.media_store import storage_path

DEFAULT_MEMORY_ROOT = "/var/lib/barong/agent-memory"
INDEX_NAME = "MEMORY.md"
CONVERSATIONS_DIR = "conversations"
STATE_DIR = "state"
MAX_CONVERSATION_LINES = 40


def memory_root() -> str:
    return os.getenv("AGENT_MEMORY_DIR", DEFAULT_MEMORY_ROOT)


def normalize_slug(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", (raw or "").strip().lower()).strip("-")
    return (slug or "untitled")[:64]


class MemoryStore:
    def __init__(self, *, username: str, index_title: str) -> None:
        self._root = Path(memory_root()) / username
        self._index_title = index_title

    def _path(self, key: str) -> Path:
        path = storage_path(self._root, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # ---------- 事实 ----------

    def load_index(self) -> str:
        path = self._root / INDEX_NAME
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def write_memory(self, *, slug: str, description: str, body: str) -> Path:
        slug = normalize_slug(slug)
        path = self._path(f"{slug}.md")
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        path.write_text(
            f"---\nname: {slug}\ndescription: {description.strip()}\nwritten: {stamp}\n---\n\n{body.strip()}\n",
            encoding="utf-8",
        )
        self._upsert_index_line(slug, description)
        return path

    def _upsert_index_line(self, slug: str, description: str) -> None:
        index = self._path(INDEX_NAME)
        lines = index.read_text(encoding="utf-8").splitlines() if index.exists() else []
        if not lines:
            lines = [f"# {self._index_title}", ""]
        marker = f"- [{slug}]({slug}.md)"
        new_line = f"{marker} — {description.strip()}"
        for i, line in enumerate(lines):
            if line.startswith(marker):
                lines[i] = new_line
                break
        else:
            lines.append(new_line)
        index.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---------- 每人隔离的对话笔记 ----------

    def load_conversation_notes(self, user_id: str) -> str:
        path = self._root / CONVERSATIONS_DIR / f"{_safe_key(user_id)}.md"
        if not path.exists():
            return ""
        return "\n".join(path.read_text(encoding="utf-8").splitlines()[-MAX_CONVERSATION_LINES:])

    def append_conversation_note(self, user_id: str, note: str) -> None:
        note = " ".join((note or "").split())
        if not note:
            return
        path = self._path(f"{CONVERSATIONS_DIR}/{_safe_key(user_id)}.md")
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"- {stamp} {note[:500]}\n")

    # ---------- 机器状态(JSON) ----------

    def load_state(self, name: str, default: Any) -> Any:
        path = self._root / STATE_DIR / f"{_safe_key(name)}.json"
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def save_state(self, name: str, value: Any) -> None:
        path = self._path(f"{STATE_DIR}/{_safe_key(name)}.json")
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)


def _safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value))[:64] or "unknown"
