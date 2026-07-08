"""Entry point for the K generation worker daemon (the `k-worker` container).

Runs a ``KGenerationJobWorker`` that polls ``k_generation_jobs`` and generates
copy / image briefs for many products in parallel. Self-contained so it does not
touch the R-W/R-A worker runtime.

Run: ``python -m backend.app.modules.k_series.product_knowledge.worker_main``
"""

from __future__ import annotations

import logging
import signal
from types import FrameType

from ....db.session import SessionLocal
from .generation_jobs import KGenerationJobWorker, requeue_stale_running

_RUNNING = True
_LOGGER = logging.getLogger("k-generation-worker")


def _handle_stop(signum: int, frame: FrameType | None) -> None:
    del signum, frame
    global _RUNNING
    _RUNNING = False
    _LOGGER.info("stop signal received; finishing current jobs then exiting")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    # A worker restart can leave jobs stuck in 'running'; release them first.
    try:
        with SessionLocal() as db:
            released = requeue_stale_running(db)
            if released:
                _LOGGER.info("requeued %d stale running job(s)", released)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("stale-job requeue failed at startup")

    worker = KGenerationJobWorker()
    _LOGGER.info(
        "K generation worker ready (concurrency=%d, poll=%.0fs)",
        worker.concurrency,
        worker.poll_seconds,
    )
    worker.run_forever(should_stop=lambda: not _RUNNING, log=_LOGGER.info)
    _LOGGER.info("K generation worker stopped")


if __name__ == "__main__":
    main()
