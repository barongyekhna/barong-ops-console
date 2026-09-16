"""amz-worker 入口:``python -m backend.app.modules.amz_series.worker_main``。"""

from __future__ import annotations

import logging
import signal
import sys

from ...db.session import SessionLocal
from .jobs import AmzWorker, requeue_stale_running

_LOGGER = logging.getLogger("amz-worker")
_RUNNING = True


def _stop(*_: object) -> None:
    global _RUNNING
    _RUNNING = False


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    with SessionLocal() as db:
        requeued = requeue_stale_running(db)
    if requeued:
        _LOGGER.info("requeued %s stale running jobs", requeued)
    AmzWorker().run_forever(should_stop=lambda: not _RUNNING, log=_LOGGER.info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
