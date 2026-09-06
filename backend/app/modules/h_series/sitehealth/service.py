"""Service layer for H site-health runs, ingest, finding review, and alerts."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ....core.target_org_guard import INTERNATIONAL_TRADE_ORG_NAME, resolve_target_org
from ...notifications.models import PNotification
from ...notifications.service import create_notification
from .models import HHealthFinding, HHealthRun

RUN_STALE_MINUTES = 30
N8N_TIMEOUT_SECONDS = 10
N8N_UNREACHABLE_DETAIL = "n8n 巡检工作流不可达，检查 N8N_H_HEALTH_WEBHOOK"


class HHealthNotFoundError(LookupError):
    """Requested H run or finding does not exist."""


class HHealthStateError(ValueError):
    """Requested finding transition is invalid for its current state."""


class HHealthDispatchError(RuntimeError):
    """The manual run was recorded, but n8n could not be reached."""


def _now() -> datetime:
    return datetime.now(UTC)


def reap_stale_runs(db: Session) -> int:
    """Mark running rows with no update for 30 minutes as failed."""

    deadline = _now() - timedelta(minutes=RUN_STALE_MINUTES)
    now = _now()
    result = db.execute(
        update(HHealthRun)
        .where(HHealthRun.status == "running")
        .where(HHealthRun.updated_at < deadline)
        .values(
            status="failed",
            error=(
                f"巡检超过 {RUN_STALE_MINUTES} 分钟无进度更新，按失联处理"
            ),
            finished_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def _post_webhook(url: str, payload: dict[str, Any]) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(  # noqa: S310 - operator-configured webhook
        request, timeout=N8N_TIMEOUT_SECONDS
    ) as response:
        response.read()


def trigger_manual_run(db: Session) -> HHealthRun:
    """Persist a manual run, then dispatch it to n8n without an open DB txn."""

    now = _now()
    run = HHealthRun(
        id=uuid4(),
        trigger="manual",
        status="running",
        started_at=now,
    )
    db.add(run)
    db.commit()

    webhook = (os.getenv("N8N_H_HEALTH_WEBHOOK") or "").strip()
    callback_base = (
        os.getenv("H_CALLBACK_BASE") or "http://console_backend:8000"
    ).strip().rstrip("/")
    payload = {
        "trigger": "manual",
        "ingest_url": f"{callback_base}/api/app/h/ingest",
        "run_id": str(run.id),
    }
    try:
        if not webhook:
            raise HHealthDispatchError(N8N_UNREACHABLE_DETAIL)
        _post_webhook(webhook, payload)
    except Exception as exc:  # noqa: BLE001 - every dispatch failure is accounted
        db.rollback()
        now = _now()
        result = db.execute(
            update(HHealthRun)
            .where(HHealthRun.id == run.id, HHealthRun.status == "running")
            .values(
                status="failed",
                finished_at=now,
                error=N8N_UNREACHABLE_DETAIL,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        db.commit()
        # Do not trust the identity-map copy retained across the pre-I/O commit:
        # a fast callback may have completed this run while dispatch timed out.
        db.expire_all()
        persisted = db.get(HHealthRun, run.id)
        if (
            int(result.rowcount or 0) == 0
            and persisted is not None
            and persisted.status in {"completed", "failed"}
        ):
            return persisted
        raise HHealthDispatchError(N8N_UNREACHABLE_DETAIL) from exc
    return run


def _alert_title(*, urls_broken: int, sitemap_ok: bool, homepage_ok: bool) -> str:
    # Homepage failure is the most severe, then sitemap failure, then dead links.
    if not homepage_ok:
        return "站点巡检发现异常：首页异常"
    if not sitemap_ok:
        return "站点巡检发现异常：sitemap 不可用"
    return f"站点巡检发现异常：死链 {urls_broken} 个"


def _alert_exists(db: Session, run_id: UUID) -> bool:
    rows = db.scalars(
        select(PNotification).where(
            PNotification.event_type == "h.health_alert",
            PNotification.source == "h_site_health",
        )
    ).all()
    expected = str(run_id)
    return any(str((row.payload or {}).get("run_id") or "") == expected for row in rows)


def _finding_lock_key(finding_type: str, url: str) -> int:
    digest = hashlib.sha256(
        f"{finding_type}\x00{url}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _lock_finding_keys(
    db: Session,
    keys: set[tuple[str, str]],
) -> None:
    """Serialize open-finding upserts across runs on PostgreSQL.

    Every transaction takes all of its stable signed-bigint keys in the same
    order, preventing two multi-finding payloads from deadlocking each other.
    Other dialects skip this PostgreSQL-specific optimization.
    """

    if db.get_bind().dialect.name != "postgresql":
        return
    lock_ids = sorted({_finding_lock_key(*key) for key in keys})
    for lock_id in lock_ids:
        db.execute(select(func.pg_advisory_xact_lock(lock_id)))


def _auto_resolve_fixed(
    db: Session,
    *,
    reported_keys: set[tuple[str, str]],
    checked_urls: list[str] | None,
    now: datetime,
) -> int:
    """本轮**确实访问过**、却没再报出来的 open 问题 —— 自动关掉。

    没有这一步，清单只进不出:2026-08-02 那批限速误报和已修好的死链全是人手动
    从库里删的。人越清越烦，最后就不看这个清单了。

    **只认执行面报上来的 `checked_urls`**，绝不用「这次没报」去推断:一轮巡检
    可能因限速或时间预算截断而漏掉一部分地址，那些地址上的老问题这次自然不会
    出现在 findings 里。靠"没报"推断会把它们一并判成已修复——那比不关更糟，
    因为人会以为没事了。

    只动 `open` 的。`acknowledged` 是人主动做的分类("我知道，不打算修")，
    系统不去改它。
    """
    if not checked_urls:
        return 0
    visited = {
        url.strip() for url in checked_urls if isinstance(url, str) and url.strip()
    }
    if not visited:
        return 0

    rows = db.scalars(
        select(HHealthFinding)
        .where(
            HHealthFinding.status == "open",
            HHealthFinding.url.in_(visited),
        )
        .with_for_update()
    ).all()

    closed = 0
    for row in rows:
        if (row.finding_type, row.url) in reported_keys:
            continue  # 这轮还在报，问题没走
        row.status = "resolved"
        row.updated_at = now
        row.detail = f"{row.detail or ''} ｜ 复检时已消失，自动关闭".strip()
        closed += 1
    return closed


def ingest_run(
    db: Session,
    *,
    run_id: UUID | None,
    result_status: str,
    error: str | None,
    summary: dict[str, Any],
    findings: list[dict[str, Any]],
    checked_urls: list[str] | None = None,
) -> tuple[HHealthRun, bool]:
    """Apply one n8n result atomically, deduplicating findings and alerts."""

    if run_id is None:
        run = HHealthRun(
            id=uuid4(),
            trigger="scheduled",
            status="running",
            started_at=_now(),
        )
        db.add(run)
        db.flush()
    else:
        # Serialize callbacks for one console-created run.  Under PostgreSQL's
        # READ COMMITTED semantics a concurrent waiter observes the first
        # callback's committed terminal state and takes the dedupe branch.
        run = db.scalar(
            select(HHealthRun)
            .where(HHealthRun.id == run_id)
            .with_for_update()
        )
        if run is None:
            raise HHealthNotFoundError("巡检运行不存在。")

    if run.status == "completed":
        return run, True

    run.status = result_status
    run.finished_at = _now()
    run.started_at = run.started_at or run.created_at or _now()
    run.urls_total = int(summary["urls_total"])
    run.urls_ok = int(summary["urls_ok"])
    run.urls_broken = int(summary["urls_broken"])
    run.urls_slow = int(summary["urls_slow"])
    run.avg_response_ms = summary.get("avg_response_ms")
    run.p95_response_ms = summary.get("p95_response_ms")
    run.sitemap_ok = bool(summary["sitemap_ok"])
    run.homepage_ok = bool(summary["homepage_ok"])
    run.summary_json = dict(summary)
    run.error = error if result_status == "failed" else None

    unique_findings: dict[tuple[str, str], dict[str, Any]] = {}
    for item in findings:
        unique_findings[(item["finding_type"], item["url"])] = item
    _lock_finding_keys(db, set(unique_findings))

    now = _now()
    for item in unique_findings.values():
        existing = db.scalar(
            select(HHealthFinding)
            .where(
                HHealthFinding.finding_type == item["finding_type"],
                HHealthFinding.url == item["url"],
                HHealthFinding.status == "open",
            )
            .order_by(HHealthFinding.created_at.desc())
            .with_for_update()
            .limit(1)
        )
        if existing is not None:
            existing.status_code = item.get("status_code")
            existing.response_ms = item.get("response_ms")
            existing.detail = item.get("detail")
            existing.updated_at = now
            continue
        db.add(
            HHealthFinding(
                id=uuid4(),
                run_id=run.id,
                finding_type=item["finding_type"],
                url=item["url"],
                status_code=item.get("status_code"),
                response_ms=item.get("response_ms"),
                detail=item.get("detail"),
                status="open",
            )
        )

    # 失败的轮次不作数——它的 checked_urls 不代表"检查过且没问题"
    if result_status == "completed":
        _auto_resolve_fixed(
            db,
            reported_keys=set(unique_findings),
            checked_urls=checked_urls,
            now=now,
        )

    should_alert = (
        run.urls_broken > 0 or not run.sitemap_ok or not run.homepage_ok
    )
    if should_alert and not _alert_exists(db, run.id):
        # 站点健康是国际贸易独立站的事，通知必须带组织归属。空 org 在通知模块里
        # 表示「全站公告」，制造公司的超管会在主页上收到贸易公司的死链告警（2026-09-06 实发）。
        trade_org = resolve_target_org(db, INTERNATIONAL_TRADE_ORG_NAME)
        create_notification(
            db,
            event_type="h.health_alert",
            level="warning",
            source="h_site_health",
            org_id=trade_org.org_id if trade_org is not None else None,
            title=_alert_title(
                urls_broken=run.urls_broken,
                sitemap_ok=run.sitemap_ok,
                homepage_ok=run.homepage_ok,
            ),
            payload={
                "run_id": str(run.id),
                "urls_broken": run.urls_broken,
                "sitemap_ok": run.sitemap_ok,
                "homepage_ok": run.homepage_ok,
            },
        )
    db.flush()
    return run, False


def transition_finding(
    db: Session,
    *,
    finding_id: UUID,
    action: str,
) -> HHealthFinding:
    # Identity must be known before taking the advisory lock, but this first
    # read intentionally locks no row.  Ingest takes advisory -> row, so the
    # transition follows the same order and cannot deadlock with it.
    identity = db.execute(
        select(HHealthFinding.finding_type, HHealthFinding.url).where(
            HHealthFinding.id == finding_id
        )
    ).one_or_none()
    if identity is None:
        raise HHealthNotFoundError("巡检发现不存在。")
    finding_key = (str(identity[0]), str(identity[1]))
    _lock_finding_keys(db, {finding_key})
    finding = db.scalar(
        select(HHealthFinding)
        .where(HHealthFinding.id == finding_id)
        .with_for_update()
    )
    if finding is None:
        raise HHealthNotFoundError("巡检发现不存在。")

    allowed_sources = {
        "acknowledge": {"open"},
        "resolve": {"open", "acknowledged"},
        "reopen": {"acknowledged", "resolved"},
    }
    target_status = {
        "acknowledge": "acknowledged",
        "resolve": "resolved",
        "reopen": "open",
    }[action]
    if finding.status not in allowed_sources[action]:
        raise HHealthStateError(
            f"当前状态 {finding.status} 不能执行 {action}。"
        )
    if action == "reopen":
        other_open_id = db.scalar(
            select(HHealthFinding.id)
            .where(
                HHealthFinding.finding_type == finding.finding_type,
                HHealthFinding.url == finding.url,
                HHealthFinding.status == "open",
                HHealthFinding.id != finding.id,
            )
            .with_for_update()
            .limit(1)
        )
        if other_open_id is not None:
            raise HHealthStateError("同一异常已有待处理记录，不能重开。")
    finding.status = target_status
    db.flush()
    return finding
