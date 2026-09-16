"""历史回填:按天要销售与流量报表(一天一份),给总览两条线和笑笑的诊断补上过去 N 天。

    python -m backend.app.modules.amz_series.backfill --store 01us --days 60 [--until 2026-09-14]

createReport 官方限速 1/分钟(突发 15),所以 60 天大约 50 分钟;一天一提交、一天一 commit,
中途断了重跑即可(upsert 幂等;已有的天用 --skip-existing 跳过)。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from ...db.session import SessionLocal
from .clients.sp_api import SpApiClient, SpApiError
from .models import AmzSalesDaily, AmzStore
from .reports_sync import STORE_TOTAL_ASIN, sync_sales_traffic_day

_LOGGER = logging.getLogger("amz.backfill")


def existing_days(db, store_code: str) -> set[date]:
    return set(db.scalars(select(AmzSalesDaily.report_date).where(AmzSalesDaily.store_code == store_code, AmzSalesDaily.child_asin == STORE_TOTAL_ASIN).distinct()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", required=True)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--until", default=None, help="最后一天(默认前天)")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--pause", type=float, default=62.0, help="两份报表之间的间隔秒数(限速 1/分钟)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    until = date.fromisoformat(args.until) if args.until else datetime.now(UTC).date() - timedelta(days=2)
    days = [until - timedelta(days=i) for i in range(args.days)]
    with SessionLocal() as db:
        store = db.get(AmzStore, args.store)
        if store is None:
            raise SystemExit(f"store {args.store} missing")
        done = existing_days(db, store.store_code) if args.skip_existing else set()
        client = SpApiClient.for_store(db, store)
        db.commit()
        ok = failed = skipped = 0
        try:
            for day in days:
                if day in done:
                    skipped += 1
                    continue
                started = time.monotonic()
                try:
                    result = sync_sales_traffic_day(db, client, store, day)
                    ok += 1
                    _LOGGER.info("%s %s rows=%s", store.store_code, day, result["rows"])
                except SpApiError as exc:
                    db.rollback()
                    failed += 1
                    _LOGGER.warning("%s %s failed: %s", store.store_code, day, exc)
                    if exc.code == "rate_limited":
                        time.sleep(120)
                elapsed = time.monotonic() - started
                if elapsed < args.pause:
                    time.sleep(args.pause - elapsed)
        finally:
            client.close()
    print(json.dumps({"store": args.store, "ok": ok, "failed": failed, "skipped": skipped, "until": until.isoformat()}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
