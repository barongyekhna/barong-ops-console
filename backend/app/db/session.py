from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
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


engine = create_engine(
    settings.database_url,
    **_engine_kwargs(settings.database_url),
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
