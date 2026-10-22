"""硬记忆:写进去就在,按问题检索(照 amz_series/work_log 的思路,换成独立站的线索)。"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ....services.data_isolation import SKIP_ORG_DATA_ISOLATION
from .constants import MEMORY_KINDS
from .models import SqhActivity, SqhMemory

# SKU(类目简写+编号,如 PSPE-001)、Woo 产品号、英文词、两个字以上的中文片段。
_SKU = re.compile(r"\b[A-Z]{2,6}-\d{2,4}\b")
_WOO_ID = re.compile(r"(?:woo|#)\s*(\d{3,6})", re.I)
_EN_WORD = re.compile(r"[A-Za-z]{4,}")
_ZH = re.compile(r"[一-鿿]{2,}")


def record(
    db: Session,
    *,
    kind: str,
    body: str,
    subject: str = "",
    refs: dict[str, Any] | None = None,
    source: str = "agent",
    actor_user_id: str | None = None,
) -> SqhMemory:
    if kind not in MEMORY_KINDS:
        raise ValueError(f"unknown_memory_kind:{kind}")
    row = SqhMemory(
        kind=kind,
        subject=subject[:200],
        body=body,
        refs=refs or {},
        source=source,
        actor_user_id=actor_user_id,
    )
    db.add(row)
    db.flush()
    return row


def log_activity(db: Session, text: str, *, kind: str = "work") -> None:
    db.add(SqhActivity(kind=kind[:16], text=text[:500]))
    db.flush()


def recent(db: Session, *, limit: int = 30, kinds: tuple[str, ...] | None = None) -> list[SqhMemory]:
    query = select(SqhMemory).order_by(SqhMemory.created_at.desc(), SqhMemory.id.desc()).limit(limit)
    if kinds:
        query = query.where(SqhMemory.kind.in_(kinds))
    return list(db.scalars(query, execution_options=SKIP_ORG_DATA_ISOLATION))


def clues(question: str) -> list[str]:
    found: list[str] = []
    found += _SKU.findall(question.upper())
    found += [m for m in _WOO_ID.findall(question)]
    found += [w.lower() for w in _EN_WORD.findall(question)][:6]
    for frag in _ZH.findall(question):
        found += [frag[i : i + 2] for i in range(0, max(1, len(frag) - 1), 2)][:6]
    seen: list[str] = []
    for item in found:
        if item and item not in seen:
            seen.append(item)
    return seen[:12]


def relevant(db: Session, question: str, *, limit: int = 12) -> list[SqhMemory]:
    """跟这个问题有关的旧记忆,新的在前。没有线索就退回最近的决定和口述。"""
    terms = clues(question)
    if not terms:
        return recent(db, limit=limit, kinds=("decision", "dictation"))
    conditions = []
    for term in terms:
        like = f"%{term}%"
        conditions += [SqhMemory.body.ilike(like), SqhMemory.subject.ilike(like)]
    query = (
        select(SqhMemory)
        .where(or_(*conditions))
        .order_by(SqhMemory.created_at.desc(), SqhMemory.id.desc())
        .limit(limit)
    )
    return list(db.scalars(query, execution_options=SKIP_ORG_DATA_ISOLATION))


def unhandled_dictations(db: Session, *, limit: int = 10) -> list[SqhMemory]:
    """owner 在办公室「交代一句」或在 C19 口述的、她还没处理的事。"""
    rows = recent(db, limit=200, kinds=("dictation",))
    return [row for row in reversed(rows) if not (row.refs or {}).get("handled")][:limit]


def mark_handled(db: Session, row: SqhMemory, *, note: str = "") -> None:
    row.refs = {**(row.refs or {}), "handled": True, "handled_note": note[:300]}
    db.add(row)
    db.flush()
