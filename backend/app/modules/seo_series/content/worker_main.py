"""seo-worker 容器的入口。

轮询 ``seo_generation_jobs``,把选题变成文章。与 geo-worker 完全独立
(独立镜像、独立容器、独立并发度)。

跑法:``python -m backend.app.modules.seo_series.content.worker_main``
"""

from __future__ import annotations

import logging
import signal
from types import FrameType

from ....db.session import SessionLocal
from .generation_jobs import SeoGenerationJobWorker, requeue_stale_running

_RUNNING = True
_LOGGER = logging.getLogger("seo-content-worker")


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
                _LOGGER.info("requeued %d stale running SEO job(s)", released)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("stale-job requeue failed at startup")

    worker = SeoGenerationJobWorker()
    _LOGGER.info("SEO worker ready (concurrency=%d)", worker.concurrency)
    worker.run_forever(should_stop=lambda: not _RUNNING, log=_LOGGER.info)
    _LOGGER.info("SEO worker stopped")


if __name__ == "__main__":
    main()
