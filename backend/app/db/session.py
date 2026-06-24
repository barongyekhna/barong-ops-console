from collections.abc import AsyncIterator, Generator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import get_settings
from ..services.data_isolation import (
    OrgDataIsolationSession,
    install_org_data_isolation_events,
)

settings = get_settings()

POOL_SIZE = settings.db_pool_size
MAX_OVERFLOW = settings.db_max_overflow
POOL_RECYCLE_SECONDS = settings.db_pool_recycle_seconds
STATEMENT_TIMEOUT_MS = settings.db_statement_timeout_ms
IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS = (
    settings.db_idle_in_transaction_session_timeout_ms
)


def _postgres_runtime_options() -> str:
    return " ".join(
        (
            f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
            "-c "
            "idle_in_transaction_session_timeout="
            f"{IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS}",
        )
    )


def _engine_kwargs(database_url: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "pool_pre_ping": True,
        "pool_recycle": POOL_RECYCLE_SECONDS,
    }
    if make_url(database_url).get_backend_name() == "postgresql":
        kwargs.update(
            {
                "pool_size": POOL_SIZE,
                "max_overflow": MAX_OVERFLOW,
                "connect_args": {
                    "options": _postgres_runtime_options(),
                },
            }
        )
    return kwargs


def _async_database_url(database_url: str) -> str | None:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        return None
    return database_url


engine = create_engine(
    settings.database_url,
    **_engine_kwargs(settings.database_url),
)
async_database_url = _async_database_url(settings.database_url)
async_engine = (
    create_async_engine(
        async_database_url,
        **_engine_kwargs(async_database_url),
    )
    if async_database_url is not None
    else None
)


def rollback_open_transaction(db: Session) -> bool:
    if not (db.in_transaction() or db.in_nested_transaction()):
        return False
    db.rollback()
    return True


class ManagedSession(OrgDataIsolationSession):
    def close(self) -> None:
        try:
            rollback_open_transaction(self)
        finally:
            super().close()


SessionLocal = sessionmaker(
    bind=engine,
    class_=ManagedSession,
    autoflush=False,
    close_resets_only=False,
    expire_on_commit=False,
)
AsyncSessionLocal = (
    async_sessionmaker(
        bind=async_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    if async_engine is not None
    else None
)
install_org_data_isolation_events()


@contextmanager
def managed_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        rollback_open_transaction(db)
        raise
    finally:
        db.close()


@contextmanager
def managed_read_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        rollback_open_transaction(db)
        db.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        rollback_open_transaction(db)
        raise
    finally:
        db.close()


def get_read_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        rollback_open_transaction(db)
        db.close()


async def rollback_open_async_transaction(db: AsyncSession) -> bool:
    if not (db.in_transaction() or db.in_nested_transaction()):
        return False
    await db.rollback()
    return True


@asynccontextmanager
async def managed_async_session() -> AsyncIterator[AsyncSession]:
    if AsyncSessionLocal is None:
        raise RuntimeError("Async DB sessions require a PostgreSQL async-capable URL.")
    async with AsyncSessionLocal() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await rollback_open_async_transaction(db)
            raise


async def get_async_db() -> AsyncIterator[AsyncSession]:
    if AsyncSessionLocal is None:
        raise RuntimeError("Async DB sessions require a PostgreSQL async-capable URL.")
    async with AsyncSessionLocal() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await rollback_open_async_transaction(db)
            raise
