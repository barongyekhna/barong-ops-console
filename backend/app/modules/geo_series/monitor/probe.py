"""Check the terrain of topic candidates **before** they are picked.

The feedback loop this closes: the first live sweep (2026-07-29) showed all four
chosen topics were "best X" questions — the home turf of gatekeeper listicles
(OutdoorGearLab, FieldMag), effectively unwinnable for a new site. Meanwhile a
mechanism question ("how long does the battery last") had no listicle on page one
at all. The operator was picking blind; this makes the ground visible at pick time.

Two cost rules, because this runs from a button on a list that can hold dozens of
candidates:

* **cached** — a candidate checked recently is not re-checked;
* **capped** — one press probes at most ``MAX_PROBE_PER_CALL`` new questions.

Probed candidates are stored inactive: they carry terrain data without joining the
recurring watch list, which stays exactly the set of topics actually written for.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...k_series.product_knowledge.scope_shim import KScopeContext
from .models import GeoMonitorQuestion, GeoMonitorResult
from .service import MonitorError, sweep_questions

logger = logging.getLogger(__name__)

MAX_PROBE_PER_CALL = 25
# A first page does not turn over quickly; a week-old reading is still a fair
# description of the terrain, and re-spending on it buys nothing.
CACHE_DAYS = 7


def normalize_question(question: str) -> str:
    return " ".join(str(question or "").split()).strip().casefold().rstrip("?")


def terrain_by_question(
    db: Session, *, cluster_id: Any | None = None
) -> dict[str, dict[str, Any]]:
    """{normalised question → latest terrain reading} for the候选 list to show."""
    query = select(GeoMonitorQuestion)
    if cluster_id is not None:
        query = query.where(GeoMonitorQuestion.cluster_id == cluster_id)
    questions = list(db.execute(query).scalars())
    if not questions:
        return {}

    by_id = {q.id: q for q in questions}
    rows = db.execute(
        select(GeoMonitorResult)
        .where(GeoMonitorResult.question_id.in_(list(by_id)))
        .order_by(GeoMonitorResult.checked_at.desc())
    ).scalars()

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        question = by_id.get(row.question_id)
        if question is None:
            continue
        key = normalize_question(question.question)
        if key in out:
            continue  # newest wins
        out[key] = {
            "attackability": row.attackability,
            "terrain": row.terrain,
            "our_position": row.our_position,
            "top_domains": [
                str(r.get("domain") or "")
                for r in (row.results_json or [])[:5]
                if isinstance(r, dict)
            ],
            "checked_at": row.checked_at.isoformat() if row.checked_at else None,
        }
    return out


def probe_candidates(
    db: Session,
    *,
    cluster_id: Any,
    questions: list[str],
    scope_context: KScopeContext,
    user: Any | None = None,
    limit: int = MAX_PROBE_PER_CALL,
) -> dict[str, Any]:
    """Ensure rows for these candidates, then check the ones lacking fresh data."""
    wanted: list[str] = []
    seen: set[str] = set()
    for raw in questions:
        text = " ".join(str(raw or "").split()).strip()
        key = normalize_question(text)
        if not text or key in seen:
            continue
        seen.add(key)
        wanted.append(text)
    if not wanted:
        raise MonitorError("没有可探测的候选问句。")

    existing = {
        normalize_question(q.question): q
        for q in db.execute(
            select(GeoMonitorQuestion).where(
                GeoMonitorQuestion.cluster_id == cluster_id
            )
        ).scalars()
    }

    fresh_after = datetime.now(UTC) - timedelta(days=CACHE_DAYS)
    fresh_ids = {
        row.question_id
        for row in db.execute(
            select(GeoMonitorResult).where(
                GeoMonitorResult.question_id.in_(
                    [q.id for q in existing.values()] or [None]
                ),
                GeoMonitorResult.checked_at >= fresh_after,
            )
        ).scalars()
    }

    to_check: list[GeoMonitorQuestion] = []
    created = 0
    cached = 0
    for text in wanted:
        key = normalize_question(text)
        row = existing.get(key)
        if row is None:
            row = GeoMonitorQuestion(
                cluster_id=cluster_id,
                question=text,
                intent=None,
                # Probe-only: terrain data without joining the recurring sweep.
                is_active=0,
                workspace_key=scope_context.workspace_key,
                business_context=scope_context.business_context,
                scope_mode=scope_context.scope_mode,
            )
            db.add(row)
            created += 1
            existing[key] = row
        elif row.id in fresh_ids:
            cached += 1
            continue
        if len(to_check) < max(0, limit):
            to_check.append(row)
    db.flush()
    db.commit()

    if not to_check:
        return {
            "checked": 0,
            "cached": cached,
            "created": created,
            "skipped_over_cap": 0,
        }

    over_cap = max(0, len(wanted) - cached - len(to_check))
    run = sweep_questions(
        db, questions=to_check, scope_context=scope_context, user=user
    )
    return {
        "checked": run.checked_count,
        "cached": cached,
        "created": created,
        "skipped_over_cap": over_cap,
        "run_status": run.status,
        "error": run.error,
    }


__all__ = [
    "CACHE_DAYS",
    "MAX_PROBE_PER_CALL",
    "normalize_question",
    "probe_candidates",
    "terrain_by_question",
]
