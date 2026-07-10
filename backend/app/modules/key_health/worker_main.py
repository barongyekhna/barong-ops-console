"""Dedicated once-per-hour key health worker."""

from __future__ import annotations

import argparse
import logging
import signal
from datetime import UTC, datetime, timedelta
from threading import Event

from .service import KeyHealthRunInProgress, run_key_health_check, scheduled_hour


logger = logging.getLogger(__name__)
stop_event = Event()


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # httpx logs the complete request URL at INFO, including provider API keys
    # passed as query parameters by APIs such as Keepa and Rainforest.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _request_stop(signum: int, frame: object) -> None:
    del signum, frame
    stop_event.set()


def _run_current_hour() -> None:
    slot = scheduled_hour()
    try:
        outcome = run_key_health_check(trigger="scheduled", scheduled_for=slot)
    except KeyHealthRunInProgress:
        logger.info("A key health run is already in progress")
        return
    logger.info(
        "Key health run %s status=%s total=%s healthy=%s warning=%s failed=%s",
        outcome.run_id,
        outcome.status,
        outcome.total_count,
        outcome.healthy_count,
        outcome.warning_count,
        outcome.failed_count,
    )


def _seconds_until_next_hour() -> float:
    now = datetime.now(UTC)
    next_hour = now.replace(minute=0, second=5, microsecond=0) + timedelta(hours=1)
    return max(1.0, (next_hour - now).total_seconds())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run hourly API key health checks")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    _configure_logging()
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    _run_current_hour()
    if args.once:
        return
    while not stop_event.wait(_seconds_until_next_hour()):
        _run_current_hour()


if __name__ == "__main__":
    main()
