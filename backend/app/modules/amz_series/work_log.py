"""员工工作日志(硬记忆):写入 + 按问题检索。

用户 2026-09-16 原话:「哪个 ASIN 在哪一个店铺里的文案最近做了什么修改、为什么,这是他的长期记忆,
必须随时能阅读到,不允许出现失忆的情况。」

所以记忆不放在模型的上下文里,也不放在她们自己写的 markdown 里,放在 ``amz_work_log`` 表:
- 规则引擎每新建一条建议 → kind=suggested(source=rule)
- 人在浮窗放行 / 驳回 / 稍后 → kind=approved / rejected / later(带原因,source=human)
- 将来执行器真改了亚马逊 → kind=executed(source=api)
- 老板在 C19 里口述「01us 的 B0XXXX 标题上周改成了…,因为…」→ kind=note(source=chat)

聊天时 ``relevant()`` 从问题里抽店铺 / ASIN / SKU / 关键词,把相关条目按时间倒序喂给她;
``recent()`` 另喂最近几条。她答得出来,是因为库里有;库里没有,她就说没有。不 commit。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from .catalog import STORE_CODES
from .constants import EMPLOYEES
from .models import AmzSuggestion, AmzWorkLog

KINDS: tuple[str, ...] = ("suggested", "approved", "rejected", "later", "executed", "note", "observation")
SOURCES: tuple[str, ...] = ("rule", "human", "api", "chat")
DECISION_KIND = {"approve": "approved", "reject": "rejected", "later": "later"}
KIND_LABELS = {
    "suggested": "提出建议",
    "approved": "放行",
    "rejected": "驳回",
    "later": "稍后",
    "executed": "已执行",
    "note": "口述记录",
    "observation": "观察",
}

_ASIN_RE = re.compile(r"\bB0[A-Z0-9]{8}\b")
_STORE_RE = re.compile(r"\b0[1-5](?:us|de)\b", re.IGNORECASE)
_SKU_RE = re.compile(r"\b[A-Z]{2,6}-[A-Z0-9]{2,}(?:-[A-Z0-9]+)*\b")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+&'-]{2,}")
_STOPWORDS = {"the", "and", "for", "with", "asin", "sku", "listing", "amazon", "what", "why", "how", "this", "that"}


def record(
    db: Session,
    *,
    employee: str,
    kind: str,
    title: str,
    why: str = "",
    store_code: str | None = None,
    subject: str = "",
    asin: str | None = None,
    sku: str | None = None,
    detail: dict[str, Any] | None = None,
    source: str = "rule",
    suggestion_id: UUID | None = None,
    actor_user_id: int | None = None,
    occurred_at: datetime | None = None,
) -> AmzWorkLog:
    employee = employee.upper()
    if employee not in EMPLOYEES:
        raise ValueError(f"unknown employee: {employee}")
    if kind not in KINDS:
        raise ValueError(f"unknown work log kind: {kind}")
    if source not in SOURCES:
        raise ValueError(f"unknown work log source: {source}")
    subject = (subject or "").strip()[:255]
    if asin is None:
        found = _ASIN_RE.search(f"{subject} {title}")
        asin = found.group(0) if found else None
    row = AmzWorkLog(
        employee=employee,
        store_code=(store_code or "").strip().lower() or None,
        kind=kind,
        subject=subject,
        asin=(asin or "").strip().upper()[:16] or None,
        sku=(sku or "").strip()[:128] or None,
        title=(title or "").strip()[:512] or "(无标题)",
        why=(why or "").strip(),
        detail_json=dict(detail or {}),
        source=source,
        suggestion_id=suggestion_id,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row


def record_decision(db: Session, *, row: AmzSuggestion, decision: str, actor_user_id: int) -> AmzWorkLog:
    """放行 / 驳回 / 稍后 → 一条带原因的日志;对象沿用当初 suggested 那条的 subject。"""
    prior = db.scalar(
        select(AmzWorkLog)
        .where(AmzWorkLog.suggestion_id == row.id, AmzWorkLog.kind == "suggested")
        .order_by(AmzWorkLog.occurred_at.desc())
    )
    subject = prior.subject if prior is not None else str((row.evidence_json or {}).get("subject") or "")
    return record(
        db,
        employee=row.employee,
        kind=DECISION_KIND[decision],
        title=row.title,
        why=row.reject_reason or "",
        store_code=row.store_code,
        subject=subject,
        detail={"action_type": row.action_type, "level": row.level, "severity": row.severity},
        source="human",
        suggestion_id=row.id,
        actor_user_id=actor_user_id,
    )


def extract_tokens(text: str) -> dict[str, list[str]]:
    """从一句话里抽出能当检索键的东西:店铺码、ASIN、SKU、英文词。中文不分词——中文关键词走标题 ILIKE 整句片段。"""
    text = text or ""
    stores = sorted({m.lower() for m in _STORE_RE.findall(text) if m.lower() in STORE_CODES})
    asins = sorted(set(_ASIN_RE.findall(text)))
    skus = sorted({m for m in _SKU_RE.findall(text) if m not in asins})
    words = sorted({w.lower() for w in _WORD_RE.findall(text) if w.lower() not in _STOPWORDS and w not in asins and w not in skus})
    return {"stores": stores, "asins": asins, "skus": skus, "words": words[:8]}


def _scope(query, *, employee: str, store_codes: list[str] | None):
    query = query.where(AmzWorkLog.employee == employee.upper())
    if store_codes is not None:
        if not store_codes:
            return query.where(false())  # 没授权 = 空集
        query = query.where(or_(AmzWorkLog.store_code.in_(store_codes), AmzWorkLog.store_code.is_(None)))
    return query


def recent(db: Session, *, employee: str, store_codes: list[str] | None, limit: int = 12) -> list[AmzWorkLog]:
    query = _scope(select(AmzWorkLog), employee=employee, store_codes=store_codes)
    return list(db.scalars(query.order_by(AmzWorkLog.occurred_at.desc()).limit(limit)))


def relevant(db: Session, *, employee: str, store_codes: list[str] | None, question: str, limit: int = 30) -> list[AmzWorkLog]:
    """跟这句话有关的条目:命中 ASIN / SKU / 店铺 / 英文词 / 中文片段任意一项,按时间倒序。"""
    tokens = extract_tokens(question)
    clauses = []
    for asin in tokens["asins"]:
        clauses.append(AmzWorkLog.asin == asin)
    for sku in tokens["skus"]:
        clauses.append(AmzWorkLog.sku.ilike(f"%{sku}%"))
        clauses.append(AmzWorkLog.subject.ilike(f"%{sku}%"))
    for word in tokens["words"]:
        clauses.append(AmzWorkLog.subject.ilike(f"%{word}%"))
        clauses.append(AmzWorkLog.title.ilike(f"%{word}%"))
    for piece in _chinese_pieces(question):
        clauses.append(AmzWorkLog.title.ilike(f"%{piece}%"))
        clauses.append(AmzWorkLog.why.ilike(f"%{piece}%"))
        clauses.append(AmzWorkLog.subject.ilike(f"%{piece}%"))
    if not clauses and not tokens["stores"]:
        return []
    query = _scope(select(AmzWorkLog), employee=employee, store_codes=store_codes)
    if tokens["stores"]:
        allowed = tokens["stores"] if store_codes is None else [s for s in tokens["stores"] if s in store_codes]
        if not allowed:
            return []
        query = query.where(AmzWorkLog.store_code.in_(allowed))
    if clauses:
        query = query.where(or_(*clauses))
    return list(db.scalars(query.order_by(AmzWorkLog.occurred_at.desc()).limit(limit)))


def timeline(db: Session, *, employee: str, store_codes: list[str] | None, subject: str, limit: int = 50) -> list[AmzWorkLog]:
    query = _scope(select(AmzWorkLog), employee=employee, store_codes=store_codes)
    like = f"%{subject.strip()}%"
    query = query.where(or_(AmzWorkLog.subject.ilike(like), AmzWorkLog.asin == subject.strip().upper(), AmzWorkLog.sku.ilike(like)))
    return list(db.scalars(query.order_by(AmzWorkLog.occurred_at.desc()).limit(limit)))


def counts(db: Session, *, employee: str, store_codes: list[str] | None) -> dict[str, int]:
    query = _scope(select(AmzWorkLog.kind, func.count()).group_by(AmzWorkLog.kind), employee=employee, store_codes=store_codes)
    return {kind: int(n) for kind, n in db.execute(query).all()}


def view(row: AmzWorkLog) -> dict[str, Any]:
    return {
        "日期": row.occurred_at.date().isoformat() if row.occurred_at else None,
        "店铺": row.store_code or "(不限店)",
        "对象": row.asin or row.sku or row.subject or "",
        "类型": KIND_LABELS.get(row.kind, row.kind),
        "做了什么": row.title,
        "为什么": row.why or "",
        "来源": {"rule": "规则", "human": "人拍板", "api": "系统执行", "chat": "老板口述"}.get(row.source, row.source),
        "谁": f"用户{row.actor_user_id}" if row.actor_user_id else "系统",
    }


_CN_SPLIT_RE = re.compile(r"为什么|是不是|怎么样|怎么|最近|什么|哪个|哪一个|哪些|以及|然后|因为|所以|但是|请问|一下|[的了是在把和跟与吗呢吧啊呀哦么]")


def _chinese_pieces(text: str) -> list[str]:
    """中文不分词:按常见虚词把连续汉字段切成 2–6 字的实词片段(「热水棒的标题为什么改了」→ 热水棒 / 标题),够 ILIKE 用。"""
    pieces: list[str] = []
    for run in re.findall(r"[一-鿿]{2,}", text or ""):
        for part in _CN_SPLIT_RE.split(run):
            part = part.strip()
            if 2 <= len(part) <= 6:
                pieces.append(part)
            elif len(part) > 6:
                pieces.append(part[:4])
                pieces.append(part[-4:])
    seen: set[str] = set()
    out = []
    for p in pieces:
        if p not in seen and p not in {"怎么样", "为什么", "什么", "最近", "做了", "修改", "文案", "店铺", "哪个", "哪一个", "怎么"}:
            seen.add(p)
            out.append(p)
    return out[:6]


def backfill_from_suggestions(db: Session) -> int:
    """给已存在的建议补 suggested 日志(上线前的 68 条)。幂等:已有 suggested 的跳过。"""
    logged = set(db.scalars(select(AmzWorkLog.suggestion_id).where(AmzWorkLog.kind == "suggested")))
    added = 0
    for row in db.scalars(select(AmzSuggestion).order_by(AmzSuggestion.created_at)):
        if row.id in logged:
            continue
        record(
            db,
            employee=row.employee,
            kind="suggested",
            title=row.title,
            why=row.why,
            store_code=row.store_code,
            subject=str((row.evidence_json or {}).get("subject") or (row.evidence_json or {}).get("term") or (row.evidence_json or {}).get("campaign") or ""),
            detail={"action_type": row.action_type, "severity": row.severity, "prediction": row.prediction},
            source="rule",
            suggestion_id=row.id,
            occurred_at=row.created_at,
        )
        added += 1
        if row.status in ("approved", "rejected", "later") and row.decided_by_user_id:
            record_decision(db, row=row, decision={"approved": "approve", "rejected": "reject", "later": "later"}[row.status], actor_user_id=int(row.decided_by_user_id))
    return added


__all__ = [
    "KINDS",
    "KIND_LABELS",
    "SOURCES",
    "backfill_from_suggestions",
    "counts",
    "extract_tokens",
    "recent",
    "record",
    "record_decision",
    "relevant",
    "timeline",
    "view",
]
