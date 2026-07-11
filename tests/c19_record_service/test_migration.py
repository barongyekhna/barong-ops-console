from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from c19_record_service.config import escape_alembic_url


ROOT = Path(__file__).resolve().parents[2]


def test_alembic_url_escaping_preserves_url_encoded_password() -> None:
    database_url = "postgresql+psycopg://user:p%40ss%2Fword@db:5432/records"
    config = Config()
    config.set_main_option("sqlalchemy.url", escape_alembic_url(database_url))

    assert config.get_main_option("sqlalchemy.url") == database_url


def test_standalone_alembic_upgrade_and_downgrade(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("C19_RECORD_DATABASE_URL", raising=False)
    database = tmp_path / "migration.sqlite"
    config = Config(str(ROOT / "c19_record_service" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    try:
        inspector = inspect(engine)
        assert {
            "chat_records",
            "chat_participant_positions",
            "chat_user_record_events",
            "record_conversation_sequences",
            "record_idempotency_ledger",
            "record_user_event_sequences",
            "record_mutation_audits",
        } <= set(inspector.get_table_names())
        foreign_keys = inspector.get_foreign_keys("chat_user_record_events")
        assert foreign_keys[0]["referred_table"] == "chat_records"
        assert foreign_keys[0]["options"].get("ondelete") == "CASCADE"
        ledger_columns = {
            column["name"]
            for column in inspector.get_columns("record_idempotency_ledger")
        }
        assert "intent_sha256" in ledger_columns
        assert "content" not in ledger_columns
        ledger_foreign_keys = inspector.get_foreign_keys(
            "record_idempotency_ledger"
        )
        assert ledger_foreign_keys[0]["options"].get("ondelete") == "SET NULL"
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(f"sqlite:///{database}")
    try:
        assert "chat_records" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
