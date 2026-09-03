"""白苏婉的记忆:服务器上只属于她一个人的一组文件。

刻意用文件而不是数据库表 —— 老板要能直接打开看、直接改、直接删。这是
「人的命令高于程序」落到记忆层:她的记忆不是黑箱,是一叠可以被划掉的纸。

    {AGENT_MEMORY_DIR}/baisuwan/
        MEMORY.md            索引,一条一行
        <slug>.md            一事一文件,带 frontmatter
        conversations/<user_id>.md   跟谁说过什么,按人隔离

她该记的:老板否决过什么+为什么、偏好、反复出现的批评、哪类题打不动。
她不该记的:数据库里已经有的东西(产品/文章/监测数据)——那些随时能查,
记下来只会过期骗人。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from ....services.media_store import storage_path
from .constants import AGENT_USERNAME, memory_root

INDEX_NAME = "MEMORY.md"
CONVERSATIONS_DIR = "conversations"

# 喂给模型的上限。记忆会一直长,不设上限迟早把上下文顶爆,而且越老的
# 越不重要。超出就截断,并在文本里明说被截断了(不能让她以为自己看全了)。
MAX_FACT_BYTES = 4_000
MAX_TOTAL_BYTES = 24_000
MAX_CONVERSATION_LINES = 40

_SLUG_ALLOWED = re.compile(r"[^a-z0-9-]+")


def _agent_root() -> Path:
    return Path(memory_root()) / AGENT_USERNAME


def normalize_slug(raw: str) -> str:
    """把模型给的标题压成安全的文件名。

    只留小写字母/数字/连字符 —— 路径分隔符、点、空格全部消掉,避免
    ``../`` 这类东西混进文件名(storage_path 还会再兜一层)。
    """
    slug = _SLUG_ALLOWED.sub("-", str(raw).strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:64] or "untitled"


def _read_text(path: Path, *, limit: int) -> str:
    try:
        data = path.read_bytes()
    except (OSError, ValueError):
        return ""
    truncated = len(data) > limit
    text = data[:limit].decode("utf-8", errors="replace")
    if truncated:
        text += "\n…（此条已截断）"
    return text


def load_index() -> str:
    root = _agent_root()
    return _read_text(root / INDEX_NAME, limit=MAX_FACT_BYTES)


def load_memory_digest() -> str:
    """索引 + 所有记忆文件正文,拼成给提示词用的一段文本。"""
    root = _agent_root()
    if not root.is_dir():
        return ""

    parts: list[str] = []
    index = load_index()
    if index.strip():
        parts.append(f"## 记忆索引\n{index.strip()}")

    total = len(index.encode("utf-8"))
    for path in sorted(root.glob("*.md")):
        if path.name == INDEX_NAME:
            continue
        if total >= MAX_TOTAL_BYTES:
            parts.append("...(记忆过多,其余条目未载入)")
            break
        body = _read_text(path, limit=MAX_FACT_BYTES)
        if not body.strip():
            continue
        total += len(body.encode("utf-8"))
        parts.append(f"## 记忆:{path.stem}\n{body.strip()}")
    return "\n\n".join(parts)


def write_memory(*, slug: str, description: str, body: str) -> Path:
    """写一条记忆并把它挂上索引。同名覆盖 —— 她修正自己的旧判断时用得上。"""
    root = _agent_root()
    safe_slug = normalize_slug(slug)
    path = storage_path(root, f"{safe_slug}.md")
    path.parent.mkdir(parents=True, exist_ok=True)

    stamped = datetime.now(UTC).date().isoformat()
    clean_description = " ".join(str(description).split())[:200]
    content = (
        "---\n"
        f"name: {safe_slug}\n"
        f"description: {clean_description}\n"
        f"written: {stamped}\n"
        "---\n\n"
        f"{str(body).strip()}\n"
    )
    path.write_text(content, encoding="utf-8")
    _upsert_index_line(root, slug=safe_slug, description=clean_description)
    return path


def _upsert_index_line(root: Path, *, slug: str, description: str) -> None:
    index_path = storage_path(root, INDEX_NAME)
    marker = f"- [{slug}]({slug}.md)"
    line = f"{marker} — {description}"

    existing: list[str] = []
    if index_path.is_file():
        existing = index_path.read_text(encoding="utf-8", errors="replace").splitlines()

    kept = [row for row in existing if not row.startswith(marker)]
    if not kept or kept[0].strip() != "# 白苏婉的记忆":
        kept = ["# 白苏婉的记忆", ""] + [row for row in kept if row.strip() != "# 白苏婉的记忆"]
    kept.append(line)
    index_path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")


def load_conversation_notes(user_id: int | str) -> str:
    """某个人的对话笔记。按人隔离 —— A 跟她说的话不漏给 B。"""
    root = _agent_root()
    path = storage_path(root, f"{CONVERSATIONS_DIR}/{_safe_user_key(user_id)}.md")
    if not path.is_file():
        return ""
    lines = _read_text(path, limit=MAX_FACT_BYTES).splitlines()
    return "\n".join(lines[-MAX_CONVERSATION_LINES:])


def append_conversation_note(user_id: int | str, note: str) -> None:
    text = " ".join(str(note).split())
    if not text:
        return
    root = _agent_root()
    path = storage_path(root, f"{CONVERSATIONS_DIR}/{_safe_user_key(user_id)}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"- {stamped} {text[:500]}\n")


def _safe_user_key(user_id: int | str) -> str:
    key = re.sub(r"[^0-9A-Za-z_-]+", "", str(user_id))
    return key or "unknown"
