from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import get_settings
from ..services.data_isolation import (
    OrgDataIsolationSession,
    install_org_data_isolation_events,
)

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(
    bind=engine,
    class_=OrgDataIsolationSession,
    autoflush=False,
    expire_on_commit=False,
)
install_org_data_isolation_events()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
