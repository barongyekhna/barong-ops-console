"""Entry point for the GEO content worker daemon (the `geo-worker` container).

Polls ``geo_generation_jobs`` and generates AI-citable cluster content from K
product facts. Standalone — does not touch the k-worker runtime.

Run: ``python -m backend.app.modules.geo_series.content.worker_main``
"""

from __future__ import annotations

import logging
import signal
from types import FrameType

from ....db.session import SessionLocal
from .generation_jobs import GeoGenerationJobWorker, requeue_stale_running

_RUNNING = True
_LOGGER = logging.getLogger("geo-content-worker")


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

    try:
        with SessionLocal() as db:
            released = requeue_stale_running(db)
            if released:
                _LOGGER.info("requeued %d stale running GEO job(s)", released)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("stale-job requeue failed at startup")

    worker = GeoGenerationJobWorker()
    _LOGGER.info("GEO workers ready (content concurrency=%d)", worker.concurrency)
    worker.run_forever(should_stop=lambda: not _RUNNING, log=_LOGGER.info)
    _LOGGER.info("GEO workers stopped")


if __name__ == "__main__":
    main()
