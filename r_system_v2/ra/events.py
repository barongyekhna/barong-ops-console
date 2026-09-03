"""Append-only R-A run event feed.

Every pipeline stage emits one small row so the frontend live deck can replay
a product's journey (prescreen → 1688 → profit gate → competition → GPT →
group) without polling the heavy job payload.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# R-A 在路由依赖层已绑死单一组织;走 API 的受管 session
# 需要单语句逃生口才不会被 C18G 拒。

from r_system_v2.ra.profit_service import _json_bind

# 与 backend.app.services.data_isolation.ORG_DATA_ISOLATION_SKIP_OPTION 同值。
# **刻意不 import 而是本地定义**:r_system_v2 → backend.app.services.data_isolation
# → backend.app.db.session → data_isolation 是一条循环链,worker 从 r_system_v2
# 这一侧进入会当场 ImportError(2026-08-31 实测 r-w-worker 崩溃循环)。
# 两边不同步的风险由 tests/backend/test_c18g_raw_sql_guard_contract.py 兜住。
SKIP_ORG_DATA_ISOLATION = {"skip_org_data_isolation": True}


STAGE_LABELS = {
    "selected": "进入流水线",
    "prescreen": "DeepSeek 量化初筛",
    "supplier_search": "1688 供应商图搜",
    "profit_gate": "利润硬门",
    "competition": "Rainforest 竞争富化",
    "channel_signals": "三渠道信号",
    "gpt_review": "GPT 终审",
    "opus_review": "Opus 复核",
    "group_assign": "入组",
    "audit": "误杀抽检",
    "run_status": "任务状态",
    "error": "错误",
}


def ensure_events_schema(db: Session) -> None:
    try:
        dialect = db.get_bind().dialect.name
    except Exception:
        dialect = "postgresql"
    json_type = "JSONB" if dialect == "postgresql" else "TEXT"
    timestamp_type = "TIMESTAMPTZ" if dialect == "postgresql" else "TEXT"
    seq_type = (
        "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
        if dialect == "postgresql"
        else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )
    db.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS ra_run_events (
              seq {seq_type},
              org_id TEXT NOT NULL,
              run_id TEXT,
              candidate_id TEXT,
              asin TEXT,
              stage TEXT NOT NULL,
              verdict TEXT,
              detail {json_type} NOT NULL DEFAULT '{{}}',
              created_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_ra_run_events_run_seq
            ON ra_run_events (run_id, seq)
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_ra_run_events_org_seq
            ON ra_run_events (org_id, seq)
            """
        )
    )


def emit_event(
    db: Session,
    *,
    org_id: str,
    run_id: str | None,
    stage: str,
    asin: str | None = None,
    candidate_id: str | None = None,
    verdict: str | None = None,
    detail: dict[str, Any] | None = None,
    commit: bool = True,
) -> None:
    """Best-effort append; event failures must never break the pipeline."""
    try:
        ensure_events_schema(db)
        db.execute(
            text(
                f"""
                INSERT INTO ra_run_events (
                  org_id, run_id, candidate_id, asin, stage, verdict, detail
                )
                VALUES (
                  :org_id, :run_id, :candidate_id, :asin, :stage, :verdict,
                  {_json_bind(db, "detail")}
                )
                """
            ),
            {
                "org_id": org_id,
                "run_id": run_id,
                "candidate_id": candidate_id,
                "asin": asin,
                "stage": stage,
                "verdict": verdict,
                "detail": json.dumps(detail or {}, ensure_ascii=False, default=str),
            },
        )
        if commit:
            db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def list_run_events(
    db: Session,
    *,
    org_id: str,
    run_id: str | None,
    after_seq: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    ensure_events_schema(db)
    bounded_limit = max(1, min(int(limit or 200), 500))
    filters = ["org_id = :org_id", "seq > :after_seq"]
    params: dict[str, Any] = {
        "org_id": org_id,
        "after_seq": max(0, int(after_seq or 0)),
        "limit": bounded_limit,
    }
    if run_id:
        filters.append("run_id = :run_id")
        params["run_id"] = run_id
    where_sql = " AND ".join(filters)
    rows = db.execute(
        text(
            f"""
            SELECT seq, run_id, candidate_id, asin, stage, verdict, detail, created_at
            FROM ra_run_events
            WHERE {where_sql}
            ORDER BY seq ASC
            LIMIT :limit
            """
        ),
        params,
        execution_options=SKIP_ORG_DATA_ISOLATION,
    ).mappings()
    items = []
    last_seq = int(params["after_seq"])
    for row in rows:
        detail = row["detail"] if isinstance(row["detail"], dict) else {}
        if isinstance(row["detail"], str):
            try:
                parsed = json.loads(row["detail"])
                detail = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                detail = {}
        seq = int(row["seq"])
        last_seq = max(last_seq, seq)
        items.append(
            {
                "seq": seq,
                "run_id": row["run_id"],
                "candidate_id": row["candidate_id"],
                "asin": row["asin"],
                "stage": row["stage"],
                "stage_label": STAGE_LABELS.get(str(row["stage"]), str(row["stage"])),
                "verdict": row["verdict"],
                "detail": detail,
                "created_at": str(row["created_at"]) if row["created_at"] else None,
            }
        )
    return {
        "items": items,
        "last_seq": last_seq,
        "count": len(items),
        "fetched_at": datetime.now(UTC).isoformat(),
    }
