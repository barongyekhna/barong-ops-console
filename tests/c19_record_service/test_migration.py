from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from c19_record_service.config import escape_alembic_url
from c19_record_service.database import DatabaseRuntime
from c19_record_service.models import RecordIdempotencyLedger
from c19_record_service.repository import _intent_sha256, append_record

from helpers import make_record


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
            "record_asset_references",
            "record_user_event_sequences",
            "record_mutation_audits",
            "record_asset_coordination",
            "record_asset_deletion_outbox",
            "record_retention_operations",
            "record_retention_batches",
            "moment_feed_sequence",
            "moments",
            "moment_audience_snapshots",
            "moment_asset_references",
            "moment_likes",
            "moment_comments",
            "moment_user_events",
        } <= set(inspector.get_table_names())
        outbox_columns = {
            column["name"]
            for column in inspector.get_columns("record_asset_deletion_outbox")
        }
        assert {
            "asset_id",
            "record_id",
            "conversation_id",
            "retention_operation_id",
            "state",
            "lease_owner",
            "lease_until",
            "authorized_at",
            "outcome",
        } <= outbox_columns
        assert "content" not in outbox_columns
        operation_columns = {
            column["name"]
            for column in inspector.get_columns("record_retention_operations")
        }
        assert {
            "approved_maximum_records",
            "approved_maximum_asset_jobs",
            "affected_count",
            "asset_jobs_enqueued_count",
            "asset_jobs_completed_count",
        } <= operation_columns
        batch_columns = {
            column["name"]
            for column in inspector.get_columns("record_retention_batches")
        }
        assert "operation_complete" in batch_columns
        foreign_keys = inspector.get_foreign_keys("chat_user_record_events")
        assert foreign_keys[0]["referred_table"] == "chat_records"
        assert foreign_keys[0]["options"].get("ondelete") == "CASCADE"
        ledger_columns = {
            column["name"]
            for column in inspector.get_columns("record_idempotency_ledger")
        }
        assert "intent_sha256" in ledger_columns
        assert "intent_version" in ledger_columns
        assert "content" not in ledger_columns
        ledger_foreign_keys = inspector.get_foreign_keys(
            "record_idempotency_ledger"
        )
        assert ledger_foreign_keys[0]["options"].get("ondelete") == "SET NULL"
        asset_columns = {
            column["name"]
            for column in inspector.get_columns("record_asset_references")
        }
        assert {
            "record_id",
            "asset_id",
            "client_asset_id",
            "kind",
            "filename",
            "media_type",
            "size_bytes",
            "sha256_hex",
            "version",
            "ordinal",
        } <= asset_columns
        assert "object_key" not in asset_columns
        assert "url" not in asset_columns
        asset_foreign_keys = inspector.get_foreign_keys(
            "record_asset_references"
        )
        assert asset_foreign_keys[0]["referred_table"] == "chat_records"
        assert asset_foreign_keys[0]["options"].get("ondelete") == "CASCADE"
        asset_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(
                "record_asset_references"
            )
        }
        assert ("record_id", "asset_id") in asset_uniques
        assert ("record_id", "ordinal") in asset_uniques
        moment_columns = {
            column["name"] for column in inspector.get_columns("moments")
        }
        assert {
            "client_moment_id",
            "author_user_id",
            "author_org_id",
            "state",
            "visibility",
            "audience_org_ids",
            "content",
            "feed_sequence",
            "publish_intent_sha256",
            "delete_pending_at",
            "deleted_at",
        } <= moment_columns
        moment_asset_columns = {
            column["name"]
            for column in inspector.get_columns("moment_asset_references")
        }
        assert {
            "moment_id",
            "asset_id",
            "client_asset_id",
            "kind",
            "filename",
            "media_type",
            "size_bytes",
            "sha256_hex",
            "version",
            "ordinal",
        } <= moment_asset_columns
        assert "object_key" not in moment_asset_columns
        assert "url" not in moment_asset_columns
        moment_event_columns = {
            column["name"] for column in inspector.get_columns("moment_user_events")
        }
        assert moment_event_columns == {
            "id",
            "user_id",
            "event_sequence",
            "event_type",
            "moment_id",
            "actor_user_id",
            "comment_id",
            "created_at",
        }
        assert "content" not in moment_event_columns
        assert "filename" not in moment_event_columns
        moment_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("moments")
        }
        assert ("author_user_id", "client_moment_id") in moment_uniques
        comment_uniques = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("moment_comments")
        }
        assert ("author_user_id", "client_comment_id") in comment_uniques
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(f"sqlite:///{database}")
    try:
        assert "chat_records" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("protected_table", "seed_statement", "seed_parameters"),
    [
        (
            "moments",
            "insert into moments "
            "(id, client_moment_id, author_user_id, author_org_id, state, "
            "visibility, audience_org_ids, content, feed_sequence, like_count, "
            "comment_count, last_like_sequence, last_comment_sequence, "
            "publish_intent_sha256, publish_intent_version, created_at, "
            "persisted_at, updated_at, published_at, delete_pending_at, "
            "deleted_at) values "
            "(:id, 'migration-moment', 'u1', null, 'draft', 'private', '[]', "
            "null, null, 0, 0, 0, 0, null, 1, :now, :now, :now, null, null, "
            "null)",
            {"id": "mom_00000000000000000000000000000001"},
        ),
        (
            "moment_comments",
            "insert into moment_comments "
            "(id, client_comment_id, moment_id, author_user_id, content, "
            "intent_sha256, status, sequence, created_at, persisted_at, "
            "updated_at, deleted_at) values "
            "(:id, 'migration-comment', :moment_id, 'u1', 'x', :sha256, "
            "'active', 1, :now, :now, :now, null)",
            {
                "id": "cmt_00000000000000000000000000000001",
                "moment_id": "mom_00000000000000000000000000000001",
                "sha256": "a" * 64,
            },
        ),
        (
            "moment_user_events",
            "insert into moment_user_events "
            "(id, user_id, event_sequence, event_type, moment_id, "
            "actor_user_id, comment_id, created_at) values "
            "(:id, 'u1', 1, 'moment_published', :moment_id, 'u1', null, :now)",
            {
                "id": "evt_00000000000000000000000000000001",
                "moment_id": "mom_00000000000000000000000000000001",
            },
        ),
    ],
)
def test_stage5_downgrade_refuses_to_drop_populated_moment_tables(
    tmp_path,
    monkeypatch,
    protected_table: str,
    seed_statement: str,
    seed_parameters: dict[str, str],
) -> None:
    monkeypatch.delenv("C19_RECORD_DATABASE_URL", raising=False)
    database = tmp_path / f"populated-{protected_table}.sqlite"
    url = f"sqlite:///{database}"
    config = Config(str(ROOT / "c19_record_service" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    now = datetime.now(UTC).isoformat()
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(seed_statement),
                {**seed_parameters, "now": now},
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="Refusing to downgrade C19 Record v3"):
        command.downgrade(config, "c19_record_20260711_02")

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert protected_table in inspector.get_table_names()
        assert "moments" in inspector.get_table_names()
        with engine.connect() as connection:
            revision = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
            preserved_count = connection.execute(
                text(f"select count(*) from {protected_table}")
            ).scalar_one()
        assert revision == "c19_record_20260712_03"
        assert preserved_count == 1
    finally:
        engine.dispose()


def test_upgrade_preserves_stage3_text_ledger_as_replayable_v1(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("C19_RECORD_DATABASE_URL", raising=False)
    database = tmp_path / "legacy-migration.sqlite"
    url = f"sqlite:///{database}"
    config = Config(str(ROOT / "c19_record_service" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "c19_record_20260711_01")

    request = make_record(1, content="legacy text")
    record_id = "11111111-1111-1111-1111-111111111111"
    persisted_at = datetime.now(UTC)
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "insert into chat_records "
                    "(id, client_message_id, conversation_id, sequence, "
                    "sender_user_id, recipient_user_ids, content_type, content, "
                    "sender_org_id, recipient_org_ids, record_metadata, created_at, "
                    "persisted_at) values "
                    "(:id, :client_message_id, :conversation_id, :sequence, "
                    ":sender_user_id, :recipient_user_ids, :content_type, :content, "
                    ":sender_org_id, :recipient_org_ids, :record_metadata, "
                    ":created_at, :persisted_at)"
                ),
                {
                    "id": record_id,
                    "client_message_id": request.client_message_id,
                    "conversation_id": request.conversation_id,
                    "sequence": 1,
                    "sender_user_id": request.sender_user_id,
                    "recipient_user_ids": json.dumps(request.recipient_user_ids),
                    "content_type": request.content_type,
                    "content": request.content,
                    "sender_org_id": request.sender_org_id,
                    "recipient_org_ids": json.dumps(request.recipient_org_ids),
                    "record_metadata": json.dumps(request.metadata),
                    "created_at": request.created_at.isoformat(),
                    "persisted_at": persisted_at.isoformat(),
                },
            )
            connection.execute(
                text(
                    "insert into record_idempotency_ledger "
                    "(sender_user_id, client_message_id, intent_sha256, "
                    "conversation_id, record_id, sequence, status, created_at, "
                    "updated_at, deleted_at) values "
                    "(:sender_user_id, :client_message_id, :intent_sha256, "
                    ":conversation_id, :record_id, 1, 'active', :created_at, "
                    ":updated_at, null)"
                ),
                {
                    "sender_user_id": request.sender_user_id,
                    "client_message_id": request.client_message_id,
                    "intent_sha256": _intent_sha256(request),
                    "conversation_id": request.conversation_id,
                    "record_id": record_id,
                    "created_at": persisted_at.isoformat(),
                    "updated_at": persisted_at.isoformat(),
                },
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    runtime = DatabaseRuntime.create(url)
    try:
        with runtime.session_factory() as session:
            replay = append_record(session, request, max_message_chars=1000)
            ledger = session.get(
                RecordIdempotencyLedger,
                (request.sender_user_id, request.client_message_id),
            )
            assert replay.replayed is True
            assert replay.record.record_id == record_id
            assert ledger is not None
            assert ledger.intent_version == 1
    finally:
        runtime.dispose()

    command.downgrade(config, "base")
    engine = create_engine(f"sqlite:///{database}")
    try:
        assert "chat_records" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
