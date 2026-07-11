from __future__ import annotations

from pathlib import Path

import pytest

from c19_record_service.config import RecordServiceSettings
from c19_record_service.cursors import CursorCodec
from c19_record_service.database import Base, DatabaseRuntime
from helpers import CURSOR_SECRET, SERVICE_TOKEN


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "record-store.sqlite"


@pytest.fixture
def runtime(database_path: Path):
    value = DatabaseRuntime.create(f"sqlite:///{database_path}")
    Base.metadata.create_all(value.engine)
    try:
        yield value
    finally:
        value.dispose()


@pytest.fixture
def settings(database_path: Path) -> RecordServiceSettings:
    return RecordServiceSettings(
        database_url=f"sqlite:///{database_path}",
        service_token=SERVICE_TOKEN,
        cursor_signing_secret=CURSOR_SECRET,
        cursor_ttl_seconds=3600,
        max_message_chars=1000,
    )


@pytest.fixture
def codec() -> CursorCodec:
    return CursorCodec(secret=CURSOR_SECRET, ttl_seconds=3600)
