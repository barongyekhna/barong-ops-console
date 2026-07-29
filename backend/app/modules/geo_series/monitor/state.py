"""What the console shows for terrain monitoring.

Answers the only three questions worth asking: where do we stand, who is holding
the page, and — the one that decides what to write next — which questions are soft
enough to be worth attacking. Sorted so the opportunities float to the top rather
than being buried in an alphabetical list.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...k_series.product_knowledge.scope_shim import KScopeContext, apply_scope_filters
from ..content.models import GeoContentCluster
from .models import GeoMonitorQuestion, GeoMonitorResult, GeoMonitorRun


def _latest_result_by_question(
    db: Session, question_ids: list[Any]
) -> dict[str, GeoMonitorResult]:
    if not question_ids:
        return {}
    rows = db.execute(
        select(GeoMonitorResult)
        .where(GeoMonitorResult.question_id.in_(question_ids))
        .order_by(GeoMonitorResult.checked_at.desc())
    ).scalars()
    latest: dict[str, GeoMonitorResult] = {}
    previous: dict[str, GeoMonitorResult] = {}
    for row in rows:
        key = str(row.question_id)
        if key not in latest:
            latest[key] = row
        elif key not in previous:
            previous[key] = row
    for key, row in previous.items():
        setattr(latest[key], "_previous", row)
    return latest


def monitor_state(
    db: Session, *, scope_context: KScopeContext, limit: int = 200
) -> dict[str, Any]:
    questions = list(
        db.execute(
            apply_scope_filters(
                select(GeoMonitorQuestion).order_by(GeoMonitorQuestion.created_at),
                GeoMonitorQuestion,
                scope_context,
            ).limit(limit)
        ).scalars()
    )
    latest = _latest_result_by_question(db, [q.id for q in questions])

    cluster_titles: dict[str, str] = {}
    cluster_ids = {q.cluster_id for q in questions if q.cluster_id}
    if cluster_ids:
        for cid, title in db.execute(
            select(GeoContentCluster.id, GeoContentCluster.title).where(
                GeoContentCluster.id.in_(cluster_ids)
            )
        ).all():
            cluster_titles[str(cid)] = str(title or "")

    items: list[dict[str, Any]] = []
    for question in questions:
        result = latest.get(str(question.id))
        previous = getattr(result, "_previous", None) if result is not None else None
        items.append(
            {
                "id": str(question.id),
                "question": question.question,
                "intent": question.intent,
                "is_active": bool(question.is_active),
                "cluster_id": str(question.cluster_id) if question.cluster_id else None,
                "cluster_title": cluster_titles.get(str(question.cluster_id), None),
                "last_checked_at": (
                    question.last_checked_at.isoformat()
                    if question.last_checked_at
                    else None
                ),
                "our_position": result.our_position if result else None,
                "previous_position": previous.our_position if previous else None,
                "attackability": result.attackability if result else None,
                "terrain": result.terrain if result else None,
                "holder_counts": (result.holder_counts_json or {}) if result else {},
                "top_results": (result.results_json or [])[:10] if result else [],
            }
        )

    # Opportunities first: soft ground we do not hold yet.
    def rank(entry: dict[str, Any]) -> tuple[int, int, int]:
        unchecked = 0 if entry["attackability"] is None else 1
        ours = 1 if entry["our_position"] else 0
        return (unchecked, ours, -(entry["attackability"] or 0))

    items.sort(key=rank)

    runs = list(
        db.execute(
            apply_scope_filters(
                select(GeoMonitorRun).order_by(GeoMonitorRun.created_at.desc()),
                GeoMonitorRun,
                scope_context,
            ).limit(5)
        ).scalars()
    )

    checked = [i for i in items if i["attackability"] is not None]
    ranked = [i for i in checked if i["our_position"]]
    return {
        "questions": items,
        "summary": {
            "watched": len(items),
            "checked": len(checked),
            "ranked": len(ranked),
            "soft_unclaimed": len(
                [i for i in checked if not i["our_position"] and i["terrain"] == "soft"]
            ),
            "best_position": min((i["our_position"] for i in ranked), default=None),
        },
        "budget": _budget_state(),
        "runs": [
            {
                "id": str(r.id),
                "status": r.status,
                "question_count": r.question_count,
                "checked_count": r.checked_count,
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in runs
        ],
    }


def _budget_state() -> dict[str, Any]:
    """Today's spend against the cap — visible in the UI, not buried in a log."""
    try:
        from r_system_v2.ra.quota_ledger import (
            PROVIDER_GEO_SERPER_MONITOR,
            daily_budget,
        )

        return {
            "provider": PROVIDER_GEO_SERPER_MONITOR,
            "daily_budget": daily_budget(PROVIDER_GEO_SERPER_MONITOR),
        }
    except Exception:  # noqa: BLE001 - the ledger is informational here
        return {}


__all__ = ["monitor_state"]
