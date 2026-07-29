"""Fill the watch list from questions we already know are real.

M2 already resolved the hard part: which questions actual buyers type. Those live
on the cluster as ``picked_questions_json`` (what the operator chose to write for)
and in the topic candidates behind it. Monitoring reuses them rather than asking
the operator to retype anything — and it means the watch list is, by construction,
the same set of questions the content was written to answer.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...k_series.product_knowledge.scope_shim import KScopeContext
from ..content.models import GeoContentCluster
from .models import GeoMonitorQuestion

logger = logging.getLogger(__name__)


def _norm(question: str) -> str:
    return " ".join(str(question or "").split()).strip().casefold().rstrip("?")


def seed_from_cluster(
    db: Session, *, cluster_id: Any, scope_context: KScopeContext
) -> tuple[int, int]:
    """(added, skipped) — idempotent: an already-watched question is never doubled."""
    cluster = db.get(GeoContentCluster, cluster_id)
    if cluster is None:
        return (0, 0)

    picked = cluster.picked_questions_json
    candidates: list[dict[str, Any]] = [
        p for p in (picked if isinstance(picked, list) else []) if isinstance(p, dict)
    ]

    existing = {
        _norm(q.question)
        for q in db.execute(
            select(GeoMonitorQuestion).where(
                GeoMonitorQuestion.cluster_id == cluster.id
            )
        ).scalars()
    }

    added = 0
    skipped = 0
    for entry in candidates:
        question = str(entry.get("question") or "").strip()
        if not question:
            continue
        if _norm(question) in existing:
            skipped += 1
            continue
        existing.add(_norm(question))
        db.add(
            GeoMonitorQuestion(
                cluster_id=cluster.id,
                question=question,
                intent=str(entry.get("intent") or "") or None,
                is_active=1,
                workspace_key=scope_context.workspace_key,
                business_context=scope_context.business_context,
                scope_mode=scope_context.scope_mode,
            )
        )
        added += 1
    db.flush()
    return (added, skipped)


__all__ = ["seed_from_cluster"]
