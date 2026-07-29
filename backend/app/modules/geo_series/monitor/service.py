"""Run a terrain sweep: ask Google what the first page looks like, per question.

Three rules this module exists to obey:

* **the ledger comes first** — a paid outbound call is consumed from the quota
  before it is made, and refunded if it never happened. The Serper burn (2026-07-22,
  50k calls over 12 days on an un-metered fallback) is the reason;
* **never hold a DB transaction across an outbound call** — the 8s
  idle-in-transaction reaper will kill it (paid for three times already);
* **a failed question is not a failed run** — one bad query must not throw away the
  observations that already succeeded.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....db.session import SessionLocal
from ...k_series.product_knowledge.scope_shim import KScopeContext
from .models import GeoMonitorQuestion, GeoMonitorResult, GeoMonitorRun
from .terrain import classify_domain, registrable_domain, summarize

logger = logging.getLogger(__name__)

SERPER_SEARCH_URL = "https://google.serper.dev/search"
# US buyers (owner is in LA and sells to the US) — a UK/CN result page would be a
# different market and a meaningless measurement.
SEARCH_LOCALE = {"gl": "us", "hl": "en"}
RESULTS_PER_QUESTION = 10
REQUEST_TIMEOUT = 30.0


class MonitorError(RuntimeError):
    """The sweep cannot run at all (no key, no budget)."""


def _now() -> datetime:
    return datetime.now(UTC)


def _serper_key(db: Session, org_id: str | None) -> str:
    from r_system_v2.core.secret_manager import SecretManager

    key = SecretManager(db_session=db).get_key("serper", org_id)
    if not str(key or "").strip():
        raise MonitorError("Serper 密钥未配置——无法监测。")
    return str(key).strip()


def fetch_first_page(*, api_key: str, question: str) -> list[dict[str, Any]]:
    """The organic first page, normalised. Raises on transport/HTTP failure."""
    response = httpx.post(
        SERPER_SEARCH_URL,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": question, "num": RESULTS_PER_QUESTION, **SEARCH_LOCALE},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(payload.get("organic") or [], start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("link") or "").strip()
        if not url:
            continue
        rows.append(
            {
                "position": int(item.get("position") or index),
                "url": url,
                "title": str(item.get("title") or "")[:300],
                "domain": registrable_domain(url),
                "holder": classify_domain(url),
            }
        )
    return rows


def active_questions(
    db: Session, *, scope_context: KScopeContext | None = None
) -> list[GeoMonitorQuestion]:
    query = select(GeoMonitorQuestion).where(GeoMonitorQuestion.is_active == 1)
    if scope_context is not None:
        from ...k_series.product_knowledge.scope_shim import apply_scope_filters

        query = apply_scope_filters(query, GeoMonitorQuestion, scope_context)
    return list(db.execute(query.order_by(GeoMonitorQuestion.created_at)).scalars())


def run_sweep(
    db: Session,
    *,
    scope_context: KScopeContext,
    user: Any | None = None,
    limit: int | None = None,
) -> GeoMonitorRun:
    """Check every active question once. Returns the finished run row."""
    from r_system_v2.ra.quota_ledger import (
        PROVIDER_GEO_SERPER_MONITOR,
        RAQuotaExhaustedError,
        ensure_quota_schema,
        refund,
        try_consume,
    )

    questions = active_questions(db, scope_context=scope_context)
    if limit is not None:
        questions = questions[: max(0, limit)]
    if not questions:
        raise MonitorError("没有在监测的问句——先从话题簇导入几条。")
    return sweep_questions(db, questions=questions, scope_context=scope_context, user=user)


def sweep_questions(
    db: Session,
    *,
    questions: list[GeoMonitorQuestion],
    scope_context: KScopeContext,
    user: Any | None = None,
) -> GeoMonitorRun:
    """The shared execution core: check exactly these rows, once each.

    Both the recurring watch-list sweep and the pre-pick candidate probe go through
    here, so the metering, the transaction discipline and the per-question failure
    handling cannot drift apart between the two entry points.
    """
    from r_system_v2.ra.quota_ledger import (
        PROVIDER_GEO_SERPER_MONITOR,
        RAQuotaExhaustedError,
        ensure_quota_schema,
        refund,
        try_consume,
    )

    if not questions:
        raise MonitorError("没有要检查的问句。")

    org_id = getattr(scope_context, "workspace_key", None)
    ensure_quota_schema(db)

    run = GeoMonitorRun(
        status="running",
        question_count=len(questions),
        checked_count=0,
        requested_by_username=getattr(user, "username", None),
        workspace_key=scope_context.workspace_key,
        business_context=scope_context.business_context,
        scope_mode=scope_context.scope_mode,
    )
    db.add(run)
    db.flush()
    run_id = run.id
    # Snapshot what the outbound loop needs, then release the transaction: every
    # call below is a network round-trip and must not sit inside one.
    plan = [(q.id, str(q.question), q.workspace_key, q.business_context, q.scope_mode)
            for q in questions]
    db.commit()

    # Resolve the key only AFTER the transaction is released. Key resolution walks
    # the api-key orchestration tables and decrypts, which is slow enough to trip
    # the 8s idle-in-transaction reaper if it runs inside an open transaction
    # (hit while building this, 2026-07-29 — the fourth time this rule has bitten).
    with SessionLocal() as key_session:
        api_key = _serper_key(key_session, org_id)

    checked = 0
    failures: list[str] = []
    for question_id, text, ws, bc, sm in plan:
        try:
            try_consume(db, PROVIDER_GEO_SERPER_MONITOR, amount=1)
        except RAQuotaExhaustedError as exc:
            failures.append(f"{text[:40]}：{exc}")
            break
        db.commit()  # release before the call

        try:
            rows = fetch_first_page(api_key=api_key, question=text)
        except Exception as exc:  # noqa: BLE001 - one bad question, not a dead run
            logger.exception("GEO monitor query failed: %s", text[:80])
            failures.append(f"{text[:40]}：{exc}")
            try:
                refund(db, PROVIDER_GEO_SERPER_MONITOR, amount=1)
                db.commit()
            except Exception:  # noqa: BLE001
                logger.exception("GEO monitor quota refund failed")
            continue

        verdict = summarize(rows)
        _persist_result(
            run_id=run_id,
            question_id=question_id,
            text=text,
            rows=rows,
            verdict=verdict,
            scope=(ws, bc, sm),
        )
        checked += 1

    with SessionLocal() as tail:
        row = tail.get(GeoMonitorRun, run_id)
        if row is not None:
            row.checked_count = checked
            row.finished_at = _now()
            if checked == 0:
                row.status = "failed"
            elif failures:
                row.status = "partial"
            else:
                row.status = "success"
            row.error = "；".join(failures[:5])[:2000] or None
            tail.commit()

    db.expire_all()
    refreshed = db.get(GeoMonitorRun, run_id)
    return refreshed if refreshed is not None else run


def _persist_result(
    *,
    run_id: UUID,
    question_id: UUID,
    text: str,
    rows: list[dict[str, Any]],
    verdict: dict[str, Any],
    scope: tuple[str, str, str],
) -> None:
    """Short-lived session per observation, so a slow query never holds a txn."""
    workspace_key, business_context, scope_mode = scope
    with SessionLocal() as session:
        session.add(
            GeoMonitorResult(
                run_id=run_id,
                question_id=question_id,
                question_text=text,
                our_position=verdict.get("our_position"),
                attackability=int(verdict.get("attackability") or 0),
                terrain=str(verdict.get("terrain") or "mixed"),
                results_json=rows,
                holder_counts_json=verdict.get("holder_counts") or {},
                checked_at=_now(),
                workspace_key=workspace_key,
                business_context=business_context,
                scope_mode=scope_mode,
            )
        )
        question = session.get(GeoMonitorQuestion, question_id)
        if question is not None:
            question.last_checked_at = _now()
        session.commit()


__all__ = [
    "MonitorError",
    "active_questions",
    "fetch_first_page",
    "run_sweep",
]
