from __future__ import annotations

from hashlib import sha256

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from backend.app.core.key_registry import metadata_for_key_type
from backend.app.db.base import Base
from backend.app.models.api_keys import ApiKeyModuleBindingRecord, ApiKeyRecord
from backend.app.models.provider_config import ProviderConfigRecord  # noqa: F401
from backend.app.services.api_key_orchestration import _encrypt_key_value
from r_system_v2.core.secret_event_bus import (
    SECRET_UPDATED,
    publish_secret_updated,
    secret_event_bus,
)
from r_system_v2.core.secret_manager import (
    K_PRODUCT_KNOWLEDGE_MODULE_ID,
    R_WAREHOUSE_MODULE_ID,
    W_SITE_OPS_MODULE_ID,
    SecretManager,
    SecretManagerError,
    SecretNotFoundError,
)
from r_system_v2.rw.ai.deepseek_screening import DeepSeekScreeningSkill
from r_system_v2.rw.providers.keepa_provider import KeepaProvider
from r_system_v2.rw.workers.secret_watch_daemon import SecretWatchDaemon


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _bind_key(
    db,
    *,
    org_id: str,
    module_id: str,
    key_alias: str,
    key_type: str,
    value: str,
) -> str:
    key_id = f"key_{org_id}_{key_alias}".replace("-", "_")
    fingerprint = sha256(value.encode("utf-8")).hexdigest()
    db.add(
        ApiKeyRecord(
            key_id=key_id,
            org_id=org_id,
            name=f"{key_alias} key",
            url="https://api.keepa.com" if key_type == "keepa" else "https://api.example.test",
            encrypted_key_value=_encrypt_key_value(value),
            key_fingerprint=fingerprint,
            key_hash_prefix=fingerprint[:12],
            status="active",
            metadata_json={
                **metadata_for_key_type(key_type),
                "runtime_state": "enabled",
            },
        )
    )
    db.add(
        ApiKeyModuleBindingRecord(
            binding_id=f"akb_{org_id}_{module_id}_{key_alias}".replace(".", "_").replace("-", "_"),
            org_id=org_id,
            module_id=module_id,
            key_id=key_id,
            key_alias=key_alias,
            status="active",
        )
    )
    db.commit()
    return key_id


def _update_key_value(db, *, key_id: str, value: str, updated_at: str = "2030-01-01 00:00:00") -> None:
    fingerprint = sha256(value.encode("utf-8")).hexdigest()
    db.execute(
        text(
            """
            UPDATE api_key_records
            SET encrypted_key_value = :encrypted_key_value,
                key_fingerprint = :key_fingerprint,
                key_hash_prefix = :key_hash_prefix,
                updated_at = :updated_at
            WHERE key_id = :key_id
            """
        ),
        {
            "encrypted_key_value": _encrypt_key_value(value),
            "key_fingerprint": fingerprint,
            "key_hash_prefix": fingerprint[:12],
            "updated_at": updated_at,
            "key_id": key_id,
        },
    )
    db.commit()


def test_secret_manager_reads_existing_api_key_bindings_and_isolates_by_org():
    db = _session()
    _bind_key(
        db,
        org_id="org_a",
        module_id=R_WAREHOUSE_MODULE_ID,
        key_alias="keepa",
        key_type="keepa",
        value="org-a-keepa",
    )
    _bind_key(
        db,
        org_id="org_b",
        module_id=R_WAREHOUSE_MODULE_ID,
        key_alias="keepa",
        key_type="keepa",
        value="org-b-keepa",
    )
    manager = SecretManager(db_session=db)

    assert manager.get_key("keepa", "org_a") == "org-a-keepa"
    assert manager.get_key("keepa", "org_b") == "org-b-keepa"
    assert manager.reload()["source"] == "api_key_orchestration"
    assert manager.get_key("keepa", "org_a") == "org-a-keepa"


def test_secret_manager_does_not_use_env_or_write_separate_secret_store(monkeypatch):
    db = _session()
    manager = SecretManager(db_session=db)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-deepseek")

    with pytest.raises(SecretNotFoundError):
        manager.get_key("deepseek", "org_a")
    with pytest.raises(SecretManagerError, match="api_key_orchestration"):
        manager.set_key("deepseek", "ignored", "org_a")

    assert manager.migrate_env_to_db("org_a")["migrated"] == []


def test_secret_manager_resolves_deepseek_from_k_series_binding_without_touching_k_code():
    db = _session()
    _bind_key(
        db,
        org_id="org_a",
        module_id=K_PRODUCT_KNOWLEDGE_MODULE_ID,
        key_alias="deepseek",
        key_type="deepseek",
        value="deepseek-from-existing-binding",
    )

    assert SecretManager(db_session=db).get_key("deepseek", "org_a") == "deepseek-from-existing-binding"


def test_secret_manager_requires_track17_key_type_before_external_use():
    db = _session()
    _bind_key(
        db,
        org_id="org_track17_wrong_type",
        module_id=W_SITE_OPS_MODULE_ID,
        key_alias="track17",
        key_type="custom",
        value="must-not-leak-to-track17",
    )
    with pytest.raises(SecretNotFoundError, match="wrong_key_type:custom"):
        SecretManager(db_session=db).get_key(
            "track17",
            "org_track17_wrong_type",
        )

    _bind_key(
        db,
        org_id="org_track17_valid",
        module_id=W_SITE_OPS_MODULE_ID,
        key_alias="track17",
        key_type="track17",
        value="valid-track17-key",
    )
    assert (
        SecretManager(db_session=db).get_key("17track", "org_track17_valid")
        == "valid-track17-key"
    )


def test_secret_manager_does_not_cross_org_from_cache():
    db = _session()
    _bind_key(
        db,
        org_id="org_a",
        module_id=K_PRODUCT_KNOWLEDGE_MODULE_ID,
        key_alias="serp",
        key_type="serp",
        value="org-a-serper",
    )
    manager = SecretManager(db_session=db)
    manager.reload()

    assert manager.get_key("serper", "org_a") == "org-a-serper"
    with pytest.raises(SecretNotFoundError) as exc_info:
        manager.get_key("serper", "org_b")
    assert "org_b:serper" in str(exc_info.value)


def test_keepa_provider_uses_secret_manager_for_existing_binding():
    db = _session()
    _bind_key(
        db,
        org_id="org_a",
        module_id=R_WAREHOUSE_MODULE_ID,
        key_alias="keepa",
        key_type="keepa",
        value="keepa-from-orchestration",
    )
    manager = SecretManager(db_session=db)

    provider = KeepaProvider(org_id="org_a", secret_manager=manager)

    assert provider.api_key == "keepa-from-orchestration"


def test_secret_update_event_reloads_worker_provider_keys():
    secret_event_bus.clear()
    db = _session()
    keepa_id = _bind_key(
        db,
        org_id="org_a",
        module_id=R_WAREHOUSE_MODULE_ID,
        key_alias="keepa",
        key_type="keepa",
        value="keepa-v1",
    )
    deepseek_id = _bind_key(
        db,
        org_id="org_a",
        module_id=K_PRODUCT_KNOWLEDGE_MODULE_ID,
        key_alias="deepseek",
        key_type="deepseek",
        value="deepseek-v1",
    )
    manager = SecretManager(db_session=db)
    provider = KeepaProvider(org_id="org_a", secret_manager=manager)
    deepseek = DeepSeekScreeningSkill(org_id="org_a", secret_manager=manager)
    daemon = SecretWatchDaemon(
        org_id="org_a",
        secret_manager=manager,
        keepa_provider=provider,
        deepseek_skill=deepseek,
    )
    daemon.start()

    _update_key_value(db, key_id=keepa_id, value="keepa-v2")
    publish_secret_updated("org_a", "keepa", source="test")
    _update_key_value(db, key_id=deepseek_id, value="deepseek-v2", updated_at="2030-01-01 00:00:01")
    publish_secret_updated("org_a", "deepseek", source="test")

    assert provider.api_key == "keepa-v2"
    assert deepseek.current_api_key() == "deepseek-v2"
    assert daemon.status.reload_count >= 2
    assert any(event.event_type == SECRET_UPDATED for event in secret_event_bus.history())
    daemon.stop()


def test_secret_manager_database_watch_invalidates_cache_and_publishes_event():
    secret_event_bus.clear()
    db = _session()
    key_id = _bind_key(
        db,
        org_id="org_a",
        module_id=R_WAREHOUSE_MODULE_ID,
        key_alias="keepa",
        key_type="keepa",
        value="keepa-v1",
    )
    manager = SecretManager(db_session=db)
    manager.poll_database_updates()
    _update_key_value(db, key_id=key_id, value="keepa-v2")

    changed = manager.poll_database_updates()

    assert changed == [{"org_id": "org_a", "service": "keepa"}]
    assert manager.get_key("keepa", "org_a") == "keepa-v2"
    assert secret_event_bus.history()[-1].source == "secret_manager.api_key_watch"


def test_secret_manager_owned_sessions_close_and_recover_after_query_failure(
    tmp_path,
    monkeypatch,
):
    database_url = f"sqlite:///{tmp_path / 'secret-manager.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    _bind_key(
        db,
        org_id="org_a",
        module_id=R_WAREHOUSE_MODULE_ID,
        key_alias="keepa",
        key_type="keepa",
        value="keepa-owned-session",
    )
    db.close()
    engine.dispose()

    manager = SecretManager(database_url=database_url)
    original_resolver = manager._resolve_from_api_key_orchestration
    fail_once = True

    def resolver(db, *, service, org_id):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            db.execute(text("SELECT * FROM intentionally_missing_table"))
        return original_resolver(db, service=service, org_id=org_id)

    monkeypatch.setattr(manager, "_resolve_from_api_key_orchestration", resolver)

    with pytest.raises(OperationalError):
        manager.get_key("keepa", "org_a")
    assert manager._owned_engine.pool.checkedout() == 0

    assert manager.get_key("keepa", "org_a") == "keepa-owned-session"
    assert manager._owned_engine.pool.checkedout() == 0

    manager.close()
    assert manager._owned_engine is None
