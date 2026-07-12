"""Alembic environment isolated from Barong and the C19 Record Service."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from c19_asset_service import models  # noqa: F401
from c19_asset_service.config import escape_alembic_url
from c19_asset_service.database import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

environment_url = os.getenv("C19_ASSET_DATABASE_URL", "").strip()
if environment_url:
    config.set_main_option("sqlalchemy.url", escape_alembic_url(environment_url))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
