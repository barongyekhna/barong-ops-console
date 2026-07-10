"""Entry point for the K generation worker daemon (the `k-worker` container).

Runs two pollers in parallel threads:
- ``KGenerationJobWorker``: polls ``k_generation_jobs`` and generates copy /
  image briefs for many products in parallel.
- ``KImageRenderWorker``: polls ``k_image_render_jobs`` and renders the
  art-direction brief's images via the I-series gpt-image-2 edit path
  (一次性作图, P 图片体系阶段 2+3).

Self-contained so it does not touch the R-W/R-A worker runtime.

Run: ``python -m backend.app.modules.k_series.product_knowledge.worker_main``
"""

from __future__ import annotations

import logging
import signal
import threading
from types import FrameType

from ....db.session import SessionLocal
from .generation_jobs import KGenerationJobWorker, requeue_stale_running
from .image_render_jobs import KImageRenderWorker, requeue_stale_render_jobs

_RUNNING = True
_LOGGER = logging.getLogger("k-generation-worker")
_RENDER_LOGGER = logging.getLogger("k-image-render-worker")


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
                _LOGGER.info("requeued %d stale running generation job(s)", released)
        with SessionLocal() as db:
            released = requeue_stale_render_jobs(db)
            if released:
                _RENDER_LOGGER.info("requeued %d stale running render job(s)", released)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("stale-job requeue failed at startup")

    generation_worker = KGenerationJobWorker()
    render_worker = KImageRenderWorker()
    _LOGGER.info(
        "K workers ready (generation concurrency=%d, render concurrency=%d)",
        generation_worker.concurrency,
        render_worker.concurrency,
    )

    render_thread = threading.Thread(
        target=lambda: render_worker.run_forever(
            should_stop=lambda: not _RUNNING,
            log=_RENDER_LOGGER.info,
        ),
        name="k-image-render",
        daemon=False,
    )
    render_thread.start()
    generation_worker.run_forever(should_stop=lambda: not _RUNNING, log=_LOGGER.info)
    render_thread.join()
    _LOGGER.info("K workers stopped")


if __name__ == "__main__":
    main()
