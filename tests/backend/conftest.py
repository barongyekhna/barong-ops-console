import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.app.core.config import Settings, get_settings
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models.operation_log import OperationLog
from backend.app.models.user import User

TEST_AUTH_SECRET = "f08-test-signing-value-not-for-production-use"


def clear_auth_tables() -> None:
    with SessionLocal() as db:
        db.execute(delete(OperationLog))
        db.execute(delete(User))
        db.commit()


@pytest.fixture
def clean_auth_tables() -> None:
    clear_auth_tables()
    yield
    clear_auth_tables()


@pytest.fixture
def auth_client(clean_auth_tables: None) -> TestClient:
    settings = Settings(
        auth_token_secret=TEST_AUTH_SECRET,
        auth_token_expire_minutes=30,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
