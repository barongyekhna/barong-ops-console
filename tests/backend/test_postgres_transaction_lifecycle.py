import pytest

from backend.app.db import session as db_session

pytestmark = pytest.mark.unit

SESSION_FACTORY_NAME = "Session" + "Local"


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0
        self.transaction_open = True

    def commit(self) -> None:
        self.commits += 1
        self.transaction_open = False

    def rollback(self) -> None:
        self.rollbacks += 1
        self.transaction_open = False

    def close(self) -> None:
        self.closes += 1

    def in_transaction(self) -> bool:
        return self.transaction_open

    def in_nested_transaction(self) -> bool:
        return False


def test_postgres_engine_enforces_statement_and_idle_transaction_timeouts() -> None:
    kwargs = db_session._engine_kwargs("postgresql+psycopg://user:pass@db/app")

    options = kwargs["connect_args"]["options"]

    assert "-c statement_timeout=5000" in options
    assert "-c idle_in_transaction_session_timeout=10000" in options
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] == 1800


def test_get_db_commits_and_closes_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSession()
    monkeypatch.setattr(db_session, SESSION_FACTORY_NAME, lambda: fake)

    dependency = db_session.get_db()

    assert next(dependency) is fake
    with pytest.raises(StopIteration):
        next(dependency)
    assert fake.commits == 1
    assert fake.rollbacks == 0
    assert fake.closes == 1


def test_get_db_rolls_back_and_closes_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSession()
    monkeypatch.setattr(db_session, SESSION_FACTORY_NAME, lambda: fake)
    dependency = db_session.get_db()

    assert next(dependency) is fake
    with pytest.raises(RuntimeError):
        dependency.throw(RuntimeError("request failed"))
    assert fake.commits == 0
    assert fake.rollbacks == 1
    assert fake.closes == 1


def test_managed_session_commits_and_closes_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSession()
    monkeypatch.setattr(db_session, SESSION_FACTORY_NAME, lambda: fake)

    with db_session.managed_session() as session:
        assert session is fake

    assert fake.commits == 1
    assert fake.rollbacks == 0
    assert fake.closes == 1


def test_managed_session_rolls_back_and_closes_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSession()
    monkeypatch.setattr(db_session, SESSION_FACTORY_NAME, lambda: fake)

    with pytest.raises(RuntimeError):
        with db_session.managed_session() as session:
            assert session is fake
            raise RuntimeError("request failed")

    assert fake.commits == 0
    assert fake.rollbacks == 1
    assert fake.closes == 1


def test_managed_read_session_rolls_back_without_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSession()
    monkeypatch.setattr(db_session, SESSION_FACTORY_NAME, lambda: fake)

    with db_session.managed_read_session() as session:
        assert session is fake

    assert fake.commits == 0
    assert fake.rollbacks == 1
    assert fake.closes == 1
