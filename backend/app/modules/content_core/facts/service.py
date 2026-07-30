"""工艺事实库的读写:写入即留痕,改版即告警。

三条规矩,都是为了同一件事——**过期的真话和编造一样有害**:

1. **实质性修改必须升版**。改错别字不升,改数值/依据/结论要升——因为引用台账
   记的是版本号,不升版就查不出谁过期。
2. **每次升版都留快照**。事后要判断"引用旧版那篇还能不能用",必须看得到旧版。
3. **只有 approved 的事实能进内容**,而且没有 ``basis``(依据)的不许批准——
   没有依据的"事实"不是事实,是主张。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ContentFactUsage, CraftFact, CraftFactRevision

logger = logging.getLogger(__name__)

# 改了这些字段才算实质性修改,才升版。改 topic 归类不影响已发布内容的正确性。
MATERIAL_FIELDS = ("claim", "detail", "value", "unit", "basis")


class CraftFactError(RuntimeError):
    """事实不满足入库/批准的条件。"""


def _snapshot(fact: CraftFact) -> dict[str, Any]:
    return {
        "topic": fact.topic,
        "claim": fact.claim,
        "detail": fact.detail,
        "value": fact.value,
        "unit": fact.unit,
        "basis": fact.basis,
        "status": fact.status,
        "version": fact.version,
    }


def create_fact(
    db: Session,
    *,
    topic: str,
    claim: str,
    scope_context: Any,
    detail: str | None = None,
    value: str | None = None,
    unit: str | None = None,
    basis: str | None = None,
    product_ids: list[str] | None = None,
    user: Any | None = None,
) -> CraftFact:
    topic = " ".join(str(topic or "").split()).strip()
    claim = " ".join(str(claim or "").split()).strip()
    if not topic or not claim:
        raise CraftFactError("topic 和 claim 都不能为空。")

    fact = CraftFact(
        topic=topic,
        claim=claim,
        detail=detail,
        value=(str(value).strip() if value else None),
        unit=(str(unit).strip() if unit else None),
        basis=basis,
        status="draft",
        version=1,
        product_ids_json=product_ids or [],
        created_by_user_id=getattr(user, "id", None),
        workspace_key=scope_context.workspace_key,
        business_context=scope_context.business_context,
        scope_mode=scope_context.scope_mode,
    )
    db.add(fact)
    db.flush()
    db.add(
        CraftFactRevision(
            fact_id=fact.id,
            version=1,
            snapshot_json=_snapshot(fact),
            change_reason="created",
            changed_by_user_id=getattr(user, "id", None),
        )
    )
    db.flush()
    return fact


def update_fact(
    db: Session,
    *,
    fact_id: UUID,
    changes: dict[str, Any],
    change_reason: str | None = None,
    user: Any | None = None,
) -> tuple[CraftFact, bool]:
    """(fact, 是否升版)。实质性修改才升版并留快照。"""
    fact = db.get(CraftFact, fact_id)
    if fact is None:
        raise CraftFactError("这条工艺事实不存在。")

    material = False
    for field, value in changes.items():
        if not hasattr(fact, field):
            continue
        new = (
            " ".join(str(value).split()).strip()
            if isinstance(value, str)
            else value
        )
        if getattr(fact, field) != new:
            if field in MATERIAL_FIELDS:
                material = True
            setattr(fact, field, new)

    if material:
        fact.version += 1
        # 改动了实质内容 → 退回待批准。已批准的旧版不该顺着改动自动生效。
        fact.status = "draft"
        fact.approved_at = None
        db.add(
            CraftFactRevision(
                fact_id=fact.id,
                version=fact.version,
                snapshot_json=_snapshot(fact),
                change_reason=change_reason or "updated",
                changed_by_user_id=getattr(user, "id", None),
            )
        )
    db.flush()
    return fact, material


def approve_fact(db: Session, *, fact_id: UUID, user: Any | None = None) -> CraftFact:
    fact = db.get(CraftFact, fact_id)
    if fact is None:
        raise CraftFactError("这条工艺事实不存在。")
    if not str(fact.basis or "").strip():
        # 没有依据的"事实"是主张。内容引擎会把它当可核事实用,所以这里挡住。
        raise CraftFactError(
            f"「{fact.claim[:30]}」没有填依据(basis)——自测?供应商规格?标准号?"
            "没有依据的事实不许批准,否则它会被当成可核事实写进文章。"
        )
    fact.status = "approved"
    fact.approved_at = datetime.now(UTC)
    db.flush()
    return fact


def approved_facts(
    db: Session, *, topics: list[str] | None = None, scope_context: Any = None
) -> list[CraftFact]:
    """能拿去写内容的事实。"""
    query = select(CraftFact).where(CraftFact.status == "approved")
    if topics:
        query = query.where(CraftFact.topic.in_(list(topics)))
    if scope_context is not None:
        from ...k_series.product_knowledge.scope_shim import apply_scope_filters

        query = apply_scope_filters(query, CraftFact, scope_context)
    return list(db.execute(query.order_by(CraftFact.topic, CraftFact.created_at)).scalars())


def record_usage(
    db: Session,
    *,
    content_kind: str,
    content_id: str,
    facts: list[CraftFact],
) -> int:
    """记下这篇内容引用了哪些事实的哪个版本。重复调用是覆盖,不是叠加。"""
    existing = {
        (u.fact_id): u
        for u in db.execute(
            select(ContentFactUsage).where(
                ContentFactUsage.content_kind == content_kind,
                ContentFactUsage.content_id == str(content_id),
            )
        ).scalars()
    }
    seen: set[UUID] = set()
    for fact in facts:
        seen.add(fact.id)
        row = existing.get(fact.id)
        if row is None:
            db.add(
                ContentFactUsage(
                    content_kind=content_kind,
                    content_id=str(content_id),
                    fact_id=fact.id,
                    fact_version=fact.version,
                )
            )
        else:
            row.fact_version = fact.version
    # 这一版不再引用的,台账里也要清掉,否则会永远报"过期"。
    for fact_id, row in existing.items():
        if fact_id not in seen:
            db.delete(row)
    db.flush()
    return len(seen)


def stale_content(db: Session, *, content_kind: str | None = None) -> list[dict[str, Any]]:
    """引用了旧版事实的内容——「需复核」清单。

    ``usage.fact_version < fact.version`` 就是全部判据。没有这张表,工艺一改就
    只能靠人肉回忆哪些文章要跟着改。
    """
    query = (
        select(
            ContentFactUsage.content_kind,
            ContentFactUsage.content_id,
            ContentFactUsage.fact_version,
            CraftFact.id,
            CraftFact.version,
            CraftFact.topic,
            CraftFact.claim,
        )
        .join(CraftFact, CraftFact.id == ContentFactUsage.fact_id)
        .where(ContentFactUsage.fact_version < CraftFact.version)
    )
    if content_kind:
        query = query.where(ContentFactUsage.content_kind == content_kind)

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for kind, cid, used_v, fact_id, cur_v, topic, claim in db.execute(query).all():
        entry = out.setdefault(
            (kind, cid), {"content_kind": kind, "content_id": cid, "stale_facts": []}
        )
        entry["stale_facts"].append(
            {
                "fact_id": str(fact_id),
                "topic": topic,
                "claim": claim,
                "used_version": used_v,
                "current_version": cur_v,
            }
        )
    return list(out.values())


def grounding_texts(facts: list[CraftFact]) -> list[str]:
    """喂给 ``guards.evidence_number_corpus`` 的文本。

    它本来就是变参函数,所以工艺事实里的数字能直接进接地语料——**护栏一行都
    不用改**,写工艺文时引用"30 分钟浸泡测试"就不会被判成编造。
    """
    out: list[str] = []
    for fact in facts:
        parts = [fact.claim, fact.detail or ""]
        if fact.value:
            parts.append(f"{fact.value} {fact.unit or ''}".strip())
        out.append(" ".join(p for p in parts if p))
    return out


__all__ = [
    "CraftFactError",
    "MATERIAL_FIELDS",
    "approve_fact",
    "approved_facts",
    "create_fact",
    "grounding_texts",
    "record_usage",
    "stale_content",
    "update_fact",
]
