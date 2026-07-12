"""Database runtime owned by the C19 asset service and worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone-aware datetime required")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    metadata = metadata


def _sqlite_connection(dbapi_connection: Any, connection_record: Any) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def build_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    options: dict[str, Any] = {"pool_pre_ping": True, "hide_parameters": True}
    if url.get_backend_name() == "sqlite":
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(database_url, **options)
    if url.get_backend_name() == "sqlite":
        event.listen(engine, "connect", _sqlite_connection)
    return engine


@dataclass(slots=True)
class DatabaseRuntime:
    engine: Engine
    session_factory: sessionmaker[Session]

    @classmethod
    def create(cls, database_url: str) -> "DatabaseRuntime":
        engine = build_engine(database_url)
        return cls(
            engine=engine,
            session_factory=sessionmaker(
                bind=engine, autoflush=False, expire_on_commit=False
            ),
        )

    def dispose(self) -> None:
        self.engine.dispose()
