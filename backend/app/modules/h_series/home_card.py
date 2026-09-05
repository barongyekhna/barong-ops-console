"""站点健康给主页的那张卡：最近一次巡检 + 哪个 worker 失联。

不调 `h_runs_list`（它会回收过期 run 并 commit），不调 `sentinel_snapshot`
（8 线程实时打 WP）。哨兵留给浮窗按需点。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...services.worker_heartbeat import list_heartbeats
from ..home.schemas import HomeCardItem, HomeCardRead
from .sitehealth.models import HHealthRun

CARD_ID = "site-health"


def load_home_card(
    db: Session,
    *,
    workspace_key: str,
    user: Any,
    permission_keys: frozenset[str],
    is_full_access: bool,
    **_: Any,
) -> HomeCardRead:
    run = db.scalar(select(HHealthRun).order_by(HHealthRun.created_at.desc()).limit(1))
    beats = list_heartbeats(db)
    stale = [beat for beat in beats if beat["stale"]]

    severity = "ok"
    if run is not None and (run.status == "failed" or not run.homepage_ok or run.urls_broken > 0):
        severity = "error"
    elif stale:
        severity = "error"
    elif run is not None and (run.urls_slow > 0 or not run.sitemap_ok):
        severity = "warn"

    items: list[HomeCardItem] = []
    if run is not None:
        status_label = {"completed": "完成", "failed": "失败", "running": "进行中"}.get(run.status, run.status)
        items.append(
            HomeCardItem(
                id=str(run.id),
                title=f"巡检 {status_label} · 断链 {run.urls_broken} · 慢页 {run.urls_slow}",
                subtitle=(
                    f"共 {run.urls_total} 页 · 首页 {'OK' if run.homepage_ok else '异常'} · "
                    f"sitemap {'OK' if run.sitemap_ok else '异常'}"
                ),
                at=run.finished_at or run.started_at or run.created_at,
                href=f"/h-site-health?run={run.id}",
            )
        )
    for beat in stale[:4]:
        silent = beat["silent_seconds"]
        items.append(
            HomeCardItem(
                id=f"worker:{beat['worker_name']}",
                title=f"{beat['worker_name']} 失联",
                subtitle=(f"{silent}s 没有成功过" if silent is not None else "从未成功"),
                at=None,
                href="/h-site-health",
            )
        )

    freshness = None
    if run is not None:
        freshness = run.finished_at or run.started_at or run.created_at
    return HomeCardRead(
        card_id=CARD_ID,
        module_key=None,
        count=(int(run.urls_broken) if run is not None else 0) + len(stale),
        items=items[:5],
        freshness=freshness or datetime.now(UTC),
        actions=[],
        extra={
            "run": (
                {
                    "id": str(run.id),
                    "status": run.status,
                    "urls_total": run.urls_total,
                    "urls_ok": run.urls_ok,
                    "urls_broken": run.urls_broken,
                    "urls_slow": run.urls_slow,
                    "homepage_ok": run.homepage_ok,
                    "sitemap_ok": run.sitemap_ok,
                    "p95_response_ms": run.p95_response_ms,
                }
                if run is not None
                else None
            ),
            "stale_workers": [
                {"worker_name": beat["worker_name"], "silent_seconds": beat["silent_seconds"]}
                for beat in stale
            ],
            "workers_total": len(beats),
        },
        severity=severity,
    )
