"""Migrate/start one explicitly selected C19 asset runtime role."""

from __future__ import annotations

import argparse
import signal
import threading
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

from .config import AssetApiSettings, GatewaySettings, WorkerSettings, escape_alembic_url


def _migrate(database_url: str) -> None:
    config = Config(str(Path(__file__).with_name("alembic.ini")))
    config.set_main_option("sqlalchemy.url", escape_alembic_url(database_url))
    command.upgrade(config, "head")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="c19-asset-service")
    parser.add_argument("role", choices=("api", "gateway", "worker"))
    args = parser.parse_args(argv)
    if args.role == "api":
        settings = AssetApiSettings.from_environment()
        _migrate(settings.database_url)
        uvicorn.run(
            "c19_asset_service.api:create_api_app_from_env",
            factory=True,
            host="0.0.0.0",
            port=8091,
            access_log=False,
            proxy_headers=False,
        )
        return
    if args.role == "gateway":
        GatewaySettings.from_environment()
        uvicorn.run(
            "c19_asset_service.gateway:create_gateway_app_from_env",
            factory=True,
            host="0.0.0.0",
            port=8092,
            access_log=False,
            proxy_headers=False,
        )
        return
    settings = WorkerSettings.from_environment()
    from .worker import AssetWorker

    worker = AssetWorker(settings)
    stop_event = threading.Event()

    def request_worker_shutdown(signum: int, frame: object) -> None:
        del signum, frame
        # Do not raise from the signal handler: the active run_once operation
        # owns a DB/filesystem transition and must reach its recovery boundary.
        stop_event.set()

    signal.signal(signal.SIGTERM, request_worker_shutdown)
    signal.signal(signal.SIGINT, request_worker_shutdown)
    try:
        worker.run_forever(stop_event=stop_event)
    finally:
        worker.close()


if __name__ == "__main__":
    main()
