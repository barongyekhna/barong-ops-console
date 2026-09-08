from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from c19_asset_service.config import (
    AssetApiSettings,
    AssetConfigurationError,
    GatewaySettings,
    WorkerSettings,
)
from c19_asset_service.database import Base
from c19_asset_service.database import DatabaseRuntime
from c19_asset_service import models  # noqa: F401
from c19_asset_service.repository import create_upload_intent, ensure_dataset_identity
from c19_asset_service.schemas import UploadIntentRequest


ROOT = Path(__file__).resolve().parents[2]


def _alembic(database_url: str) -> Config:
    config = Config(str(ROOT / "c19_asset_service" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_initial_migration_matches_models_and_downgrades(tmp_path, monkeypatch):
    monkeypatch.delenv("C19_ASSET_DATABASE_URL", raising=False)
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = _alembic(database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    expected = {
        "alembic_version",
        "asset_dataset_identity",
        "chat_assets",
        "asset_transfer_tickets",
        "asset_audit_events",
    }
    assert set(inspect(engine).get_table_names()) == expected
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, Base.metadata) == []
    engine.dispose()
    command.downgrade(config, "base")
    engine = create_engine(database_url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def _stage4_intent_hash(
    *, client_asset_id: str, conversation_id: str, owner_user_id: str
) -> str:
    canonical = json.dumps(
        {
            "client_asset_id": client_asset_id,
            "conversation_id": conversation_id,
            "filename": "legacy.png",
            "kind": "image",
            "media_type": "image/png",
            "owner_user_id": owner_user_id,
            "sha256_hex": "a" * 64,
            "size_bytes": 17,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _insert_stage4_asset(
    connection,
    *,
    suffix: str,
    binding_status: str,
    client_message_id: str | None,
    record_id: str | None,
) -> str:
    asset_id = "att_" + suffix * 32
    now = datetime.now(UTC)
    client_asset_id = f"legacy-{suffix}"
    owner_user_id = "legacy-owner"
    connection.execute(
        text(
            """
            INSERT INTO chat_assets (
              asset_id, client_asset_id, owner_user_id, conversation_id, kind,
              intent_sha256, filename, media_type, declared_size_bytes,
              declared_sha256_hex, actual_size_bytes, actual_sha256_hex,
              active_object_key, status, version, binding_status,
              client_message_id, record_id, requested_at, created_at, updated_at,
              activated_at, prepared_at, committed_at
            ) VALUES (
              :asset_id, :client_asset_id, :owner_user_id, 'legacy-conversation',
              'image', :intent_sha256, 'legacy.png', 'image/png', 17, :digest,
              17, :digest, :object_key, 'active', 3, :binding_status,
              :client_message_id, :record_id, :now, :now, :now, :now,
              :prepared_at, :committed_at
            )
            """
        ),
        {
            "asset_id": asset_id,
            "client_asset_id": client_asset_id,
            "owner_user_id": owner_user_id,
            "intent_sha256": _stage4_intent_hash(
                client_asset_id=client_asset_id,
                conversation_id="legacy-conversation",
                owner_user_id=owner_user_id,
            ),
            "digest": "a" * 64,
            "object_key": f"{suffix * 2}/{suffix * 2}/{suffix * 28}",
            "binding_status": binding_status,
            "client_message_id": client_message_id,
            "record_id": record_id,
            "now": now,
            "prepared_at": now if client_message_id else None,
            "committed_at": now if record_id else None,
        },
    )
    return asset_id


def test_stage4_rows_and_ticket_hashes_backfill_without_loss(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'stage4-upgrade.db'}"
    config = _alembic(database_url)
    command.upgrade(config, "c19_asset_20260711_01")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        unbound = _insert_stage4_asset(
            connection,
            suffix="1",
            binding_status="unbound",
            client_message_id=None,
            record_id=None,
        )
        prepared = _insert_stage4_asset(
            connection,
            suffix="2",
            binding_status="prepared",
            client_message_id="legacy-message-prepared",
            record_id=None,
        )
        committed = _insert_stage4_asset(
            connection,
            suffix="3",
            binding_status="committed",
            client_message_id="legacy-message-committed",
            record_id="legacy-record",
        )
        connection.execute(
            text(
                """
                INSERT INTO asset_transfer_tickets (
                  ticket_id, ticket_sha256, asset_id, direction, owner_user_id,
                  reader_user_id, conversation_id, record_id, variant,
                  disposition, asset_version, max_uses, used_count, created_at,
                  expires_at
                ) VALUES (
                  'legacy-ticket-id', :ticket_hash, :asset_id, 'download',
                  'legacy-owner', 'legacy-reader', 'legacy-conversation',
                  'legacy-record', 'original', 'attachment', 3, 12, 2,
                  :now, :now
                )
                """
            ),
            {
                "ticket_hash": "f" * 64,
                "asset_id": committed,
                "now": datetime.now(UTC),
            },
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT asset_id, usage, scope_id, binding_client_id, "
                "bound_resource_id, active_object_key, intent_sha256 "
                "FROM chat_assets ORDER BY asset_id"
            )
        ).mappings().all()
        assert [row["asset_id"] for row in rows] == [unbound, prepared, committed]
        assert {row["usage"] for row in rows} == {"chat_message"}
        assert {row["scope_id"] for row in rows} == {"legacy-conversation"}
        assert rows[0]["binding_client_id"] is None
        assert rows[1]["binding_client_id"] == "legacy-message-prepared"
        assert rows[1]["bound_resource_id"] is None
        assert rows[2]["binding_client_id"] == "legacy-message-committed"
        assert rows[2]["bound_resource_id"] == "legacy-record"
        assert rows[2]["active_object_key"] == "33/33/" + "3" * 28
        assert rows[2]["intent_sha256"] == _stage4_intent_hash(
            client_asset_id="legacy-3",
            conversation_id="legacy-conversation",
            owner_user_id="legacy-owner",
        )
        ticket = connection.execute(
            text(
                "SELECT ticket_sha256, usage, scope_id, bound_resource_id, "
                "used_count FROM asset_transfer_tickets"
            )
        ).mappings().one()
        assert dict(ticket) == {
            "ticket_sha256": "f" * 64,
            "usage": "chat_message",
            "scope_id": "legacy-conversation",
            "bound_resource_id": "legacy-record",
            "used_count": 2,
        }
    engine.dispose()

    runtime = DatabaseRuntime.create(database_url)
    try:
        settings = AssetApiSettings(
            database_url=database_url,
            service_token="s" * 32,
            gateway_token="g" * 32,
            dataset_id="migration-replay",
        )
        request = UploadIntentRequest(
            client_asset_id="legacy-3",
            owner_user_id="legacy-owner",
            conversation_id="legacy-conversation",
            kind="image",
            filename="legacy.png",
            media_type="image/png",
            size_bytes=17,
            sha256_hex="a" * 64,
            requested_at=datetime.now(UTC),
        )
        with runtime.session_factory() as session:
            ensure_dataset_identity(session, settings.dataset_id)
        with runtime.session_factory() as session:
            replay = create_upload_intent(session, request, settings)
        assert replay.asset.asset_id == committed
        assert replay.asset.conversation_id == "legacy-conversation"
        assert replay.upload_ticket is None
    finally:
        runtime.dispose()


def test_scope_migration_downgrade_refuses_moment_data(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'moment-downgrade.db'}"
    config = _alembic(database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO chat_assets (
                  asset_id, client_asset_id, owner_user_id, usage, scope_id,
                  kind, intent_sha256, filename, media_type,
                  declared_size_bytes, declared_sha256_hex, status, version,
                  binding_status, requested_at, created_at, updated_at
                ) VALUES (
                  :asset_id, 'moment-client', 'owner', 'moment_image', :scope,
                  'image', :intent, 'moment.png', 'image/png', 5, :digest,
                  'pending_upload', 1, 'unbound', :now, :now, :now
                )
                """
            ),
            {
                "asset_id": "att_" + "d" * 32,
                "scope": "mom_" + "e" * 32,
                "intent": "b" * 64,
                "digest": "c" * 64,
                "now": now,
            },
        )
    engine.dispose()
    with pytest.raises(RuntimeError, match="would discard Moment"):
        command.downgrade(config, "c19_asset_20260711_01")


def test_role_configuration_isolated_and_fail_closed(tmp_path, monkeypatch):
    names = [
        "C19_ASSET_DATABASE_URL",
        "C19_ASSET_SERVICE_TOKEN",
        "C19_ASSET_GATEWAY_TOKEN",
        "C19_ASSET_DATASET_ID",
        "C19_ASSET_API_URL",
        "C19_ASSET_INCOMING_ROOT",
        "C19_ASSET_ACTIVE_ROOT",
        "C19_ASSET_QUARANTINE_ROOT",
        "C19_ASSET_CLAMD_HOST",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(AssetConfigurationError):
        AssetApiSettings.from_environment()
    monkeypatch.setenv("C19_ASSET_DATABASE_URL", "sqlite:///asset.db")
    monkeypatch.setenv("C19_ASSET_SERVICE_TOKEN", "s" * 32)
    monkeypatch.setenv("C19_ASSET_GATEWAY_TOKEN", "g" * 32)
    monkeypatch.setenv("C19_ASSET_DATASET_ID", "dataset-1")
    api = AssetApiSettings.from_environment()
    assert api.dataset_id == "dataset-1"
    assert api.owner_reserved_file_limit == 2_000
    assert api.owner_reserved_byte_limit == 20 * 1024 * 1024 * 1024
    assert api.global_reserved_file_limit == 100_000
    assert api.global_reserved_byte_limit == 100 * 1024 * 1024 * 1024
    assert api.thumbnail_max_bytes == 2 * 1024 * 1024
    # API configuration does not need or expose any object-volume path.
    assert not hasattr(api, "active_root")
    monkeypatch.setenv("C19_ASSET_API_URL", "http://asset-api:8091")
    monkeypatch.setenv("C19_ASSET_INCOMING_ROOT", str(tmp_path / "incoming"))
    monkeypatch.setenv("C19_ASSET_ACTIVE_ROOT", str(tmp_path / "active"))
    gateway = GatewaySettings.from_environment()
    assert not hasattr(gateway, "database_url")
    monkeypatch.setenv("C19_ASSET_QUARANTINE_ROOT", str(tmp_path / "quarantine"))
    monkeypatch.setenv("C19_ASSET_CLAMD_HOST", "clamd")
    worker = WorkerSettings.from_environment()
    assert not hasattr(worker, "service_token")
    assert worker.dataset_id == api.dataset_id
    assert worker.thumbnail_max_bytes == api.thumbnail_max_bytes
    with pytest.raises(AssetConfigurationError):
        AssetApiSettings(
            database_url="sqlite:///asset.db",
            service_token="same" * 10,
            gateway_token="same" * 10,
            dataset_id="dataset-1",
        )


def test_container_has_fixed_non_root_identity_and_explicit_roles():
    dockerfile = (ROOT / "c19_asset_service" / "Dockerfile").read_text()
    start = (ROOT / "c19_asset_service" / "start.py").read_text()
    gateway = (ROOT / "c19_asset_service" / "gateway.py").read_text()
    assert "--uid 10001 --gid 10001" in dockerfile
    assert "USER c19asset" in dockerfile
    assert 'CMD ["python", "-m", "c19_asset_service.start", "api"]' in dockerfile
    assert 'choices=("api", "gateway", "worker")' in start
    # Only the API branch migrates; the worker waits for the API-owned schema.
    assert start.count("_migrate(settings.database_url)") == 1
    assert "trust_env=False" in gateway
    assert '"/api/backend/c19-assets/u/{ticket}"' in gateway
    assert '"/api/backend/c19-assets/d/{ticket}"' in gateway


def test_api_role_has_no_object_volume_settings_and_gateway_has_no_orm_imports():
    api_source = (ROOT / "c19_asset_service" / "api.py").read_text()
    gateway_source = (ROOT / "c19_asset_service" / "gateway.py").read_text()
    assert "incoming_root" not in api_source
    assert "active_root" not in api_source
    assert "sqlalchemy" not in gateway_source
    assert "DatabaseRuntime" not in gateway_source
