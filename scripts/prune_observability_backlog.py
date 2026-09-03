#!/usr/bin/env python
"""把两张观测表的存量老数据分批清掉。

**为什么要单独一个脚本**：`event_collector` 里已经挂了持续清理（每小时一轮、
每轮最多 4 批 × 5000 行），但那是给日常增量用的。存量是 107 万行、约 3 GB，
按那个节奏要跑很久。这个脚本让你一次把历史包袱清完，之后交给后台维持。

**为什么必须分批**：`event_streams` 与 `storage_events` 是全库写得最频繁的
两张表。一条扫 90 万行的 DELETE 会长时间持锁、把表撑肿，还会把正在写入的
请求拖住。所以每批 5000 行、批间让路，随时可以 Ctrl-C 停下，已删的不回滚。

**顺序不能反**：storage_events.record_id 外键指向 event_streams.record_id，
删除规则是 NO ACTION —— 先删父表一行都删不掉，而且是静默删不掉。

默认**只统计不删**。真要删加 --execute。
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 与 check_worker_heartbeats.py / backfill_notification_org.py 同一套写法：
# 容器里 /app 是包根，脚本在 /app/scripts 下。
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import text  # noqa: E402

from backend.app.db.session import SessionLocal  # noqa: E402
from backend.app.services.data_isolation import (  # noqa: E402
    SKIP_ORG_DATA_ISOLATION,
    without_org_data_isolation,
)
from backend.app.services.event_collector import (  # noqa: E402
    DEFAULT_EVENT_RETENTION_DAYS,
    EVENT_RETENTION_BATCH_ROWS,
)

# 先子后父。
TABLES = ("storage_events", "event_streams")


def _counts(db, cutoff: datetime) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for table in TABLES:
        total = db.scalar(
            text(f"SELECT count(*) FROM {table}"),
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )
        expired = db.scalar(
            text(f"SELECT count(*) FROM {table} WHERE created_at < :cutoff"),
            {"cutoff": cutoff},
            execution_options=SKIP_ORG_DATA_ISOLATION,
        )
        out[table] = (int(total or 0), int(expired or 0))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_EVENT_RETENTION_DAYS,
        help=f"保留多少天（默认 {DEFAULT_EVENT_RETENTION_DAYS}）",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="真的删。不加就只统计。",
    )
    parser.add_argument(
        "--pause-ms",
        type=int,
        default=200,
        help="批间停顿毫秒数，给写入让路（默认 200）",
    )
    args = parser.parse_args()

    if args.days <= 0:
        print("--days 必须大于 0。要关闭清理请设 EVENT_RETENTION_DAYS=0，别用这个脚本。")
        return 2

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    print(f"留存窗：{args.days} 天（{cutoff.isoformat()} 之前的删掉）")

    with without_org_data_isolation():
        with SessionLocal() as db:
            before = _counts(db, cutoff)
        for table, (total, expired) in before.items():
            share = (expired * 100 / total) if total else 0
            print(f"  {table:<16} 共 {total:>9,} 行，其中过期 {expired:>9,} 行（{share:.0f}%）")

        if not args.execute:
            print("\n只统计，没有删除。确认无误后加 --execute。")
            return 0

        started = time.monotonic()
        for table in TABLES:
            removed_total = 0
            while True:
                with SessionLocal() as db:
                    result = db.execute(
                        text(
                            f"""
                            DELETE FROM {table}
                            WHERE ctid IN (
                                SELECT ctid FROM {table}
                                WHERE created_at < :cutoff
                                LIMIT :batch
                            )
                            """
                        ),
                        {"batch": EVENT_RETENTION_BATCH_ROWS, "cutoff": cutoff},
                        execution_options=SKIP_ORG_DATA_ISOLATION,
                    )
                    db.commit()
                removed = result.rowcount or 0
                removed_total += removed
                if removed:
                    print(
                        f"  {table}: 已删 {removed_total:,} 行"
                        f"（{time.monotonic() - started:.0f}s）",
                        flush=True,
                    )
                # 只有删到 0 行才算删完 —— 见 event_collector.prune_expired 的说明：
                # 并发写入下一批删得少于 LIMIT 是常态，不代表没有更多了。
                # 2026-09-02 这个脚本就因为写成 `< BATCH` 而提前收工，
                # 报「完成」时还剩 19 万行没删。
                if removed == 0:
                    break
                time.sleep(args.pause_ms / 1000)
            print(f"{table} 完成，共删 {removed_total:,} 行。")

        with SessionLocal() as db:
            after = _counts(db, cutoff)
        print("\n清理后：")
        for table, (total, expired) in after.items():
            print(f"  {table:<16} 共 {total:>9,} 行，剩余过期 {expired:>9,} 行")

    print("\n磁盘不会立刻释放：删除只是标记死元组，等 autovacuum 回收。")
    print("要立刻还给操作系统需要 VACUUM FULL（会锁表），一般不必。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
