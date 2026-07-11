"""Migrate the private schema, then start the internal HTTP process."""

from __future__ import annotations

from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

from .config import RecordServiceSettings, escape_alembic_url


def main() -> None:
    settings = RecordServiceSettings.from_environment()
    config = Config(str(Path(__file__).with_name("alembic.ini")))
    config.set_main_option("sqlalchemy.url", escape_alembic_url(settings.database_url))
    command.upgrade(config, "head")
    uvicorn.run(
        "c19_record_service.app:create_app_from_env",
        factory=True,
        host="0.0.0.0",
        port=8090,
        access_log=True,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
