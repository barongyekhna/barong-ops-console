from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from c19_asset_service.consistency import (
    AssetConsistencyError,
    _database_url_for_name,
    assert_consistent_active_dataset,
    backup_drain_blocker_count,
    main as consistency_main,
    render_manifest,
)
from c19_asset_service.models import Asset

from c19_asset_test_helpers import moment_upload_payload, upload_payload


def _activate_for_consistency(
    client,
    app,
    service_headers,
    active_root,
    *,
    body: bytes = b"manifest original\n",
    object_key: str = "aa/bb/" + "c" * 28,
    thumbnail: bytes | None = None,
) -> str:
    payload = upload_payload(body, client_asset_id="manifest-asset")
    response = client.post(
        "/v1/upload-intents", headers=service_headers, json=payload
    )
    assert response.status_code == 201
    asset_id = response.json()["asset"]["asset_id"]
    object_path = active_root / object_key
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_bytes(body)
    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        asset.status = "active"
        asset.incoming_object_key = None
        asset.active_object_key = object_key
        asset.actual_size_bytes = len(body)
        asset.actual_sha256_hex = hashlib.sha256(body).hexdigest()
        asset.activated_at = datetime.now(UTC)
        asset.updated_at = asset.activated_at
        if thumbnail is not None:
            thumbnail_key = "dd/ee/" + "f" * 28
            thumbnail_path = active_root / thumbnail_key
            thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
            thumbnail_path.write_bytes(thumbnail)
            asset.thumbnail_object_key = thumbnail_key
            asset.thumbnail_size_bytes = len(thumbnail)
            asset.thumbnail_sha256_hex = hashlib.sha256(thumbnail).hexdigest()
            asset.thumbnail_media_type = "image/png"
        session.commit()
    return asset_id


def test_consistency_manifest_is_exact_sorted_db_and_filesystem_equivalence(
    client, app, api_settings, service_headers, tmp_path
):
    active_root = tmp_path / "active"
    original = b"manifest original\n"
    thumbnail = b"safe thumbnail\n"
    _activate_for_consistency(
        client,
        app,
        service_headers,
        active_root,
        body=original,
        thumbnail=thumbnail,
    )
    with app.state.database.session_factory() as session:
        entries = assert_consistent_active_dataset(
            session,
            dataset_id=api_settings.dataset_id,
            active_root=active_root,
        )

    assert render_manifest(entries) == (
        f"{hashlib.sha256(original).hexdigest()}\t{len(original)}\t"
        f"aa/bb/{'c' * 28}\n"
        f"{hashlib.sha256(thumbnail).hexdigest()}\t{len(thumbnail)}\t"
        f"dd/ee/{'f' * 28}\n"
    )


def test_consistency_manifest_covers_chat_and_moment_objects_together(
    client, app, api_settings, service_headers, tmp_path
):
    active_root = tmp_path / "active"
    chat_body = b"chat object"
    moment_body = b"moment image object"
    _activate_for_consistency(
        client,
        app,
        service_headers,
        active_root,
        body=chat_body,
        object_key="11/22/" + "3" * 28,
    )
    response = client.post(
        "/v1/moment-assets/upload-intents",
        headers=service_headers,
        json=moment_upload_payload(
            moment_body, client_asset_id="manifest-moment-asset"
        ),
    )
    assert response.status_code == 201
    asset_id = response.json()["asset"]["asset_id"]
    moment_key = "44/55/" + "6" * 28
    moment_path = active_root / moment_key
    moment_path.parent.mkdir(parents=True, exist_ok=True)
    moment_path.write_bytes(moment_body)
    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None and asset.usage == "moment_image"
        asset.status = "active"
        asset.incoming_object_key = None
        asset.active_object_key = moment_key
        asset.actual_size_bytes = len(moment_body)
        asset.actual_sha256_hex = hashlib.sha256(moment_body).hexdigest()
        asset.activated_at = datetime.now(UTC)
        asset.updated_at = asset.activated_at
        session.commit()
    with app.state.database.session_factory() as session:
        entries = assert_consistent_active_dataset(
            session,
            dataset_id=api_settings.dataset_id,
            active_root=active_root,
        )
    assert set(entries) == {"11/22/" + "3" * 28, moment_key}
    assert entries[moment_key].sha256_hex == hashlib.sha256(moment_body).hexdigest()


@pytest.mark.parametrize("failure", ("orphan", "missing", "digest"))
def test_consistency_rejects_orphan_missing_and_content_mismatch(
    failure, client, app, api_settings, service_headers, tmp_path
):
    active_root = tmp_path / "active"
    _activate_for_consistency(client, app, service_headers, active_root)
    object_path = active_root / "aa/bb" / ("c" * 28)
    if failure == "orphan":
        orphan = active_root / "11/22" / ("3" * 28)
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(b"unreferenced")
    elif failure == "missing":
        object_path.unlink()
    else:
        object_path.write_bytes(b"same path, changed bytes")

    with app.state.database.session_factory() as session:
        with pytest.raises(AssetConsistencyError):
            assert_consistent_active_dataset(
                session,
                dataset_id=api_settings.dataset_id,
                active_root=active_root,
            )


def test_consistency_rejects_incomplete_thumbnail_metadata(
    client, app, api_settings, service_headers, tmp_path
):
    active_root = tmp_path / "active"
    asset_id = _activate_for_consistency(
        client, app, service_headers, active_root
    )
    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        asset.thumbnail_size_bytes = 123
        session.commit()

    with app.state.database.session_factory() as session:
        with pytest.raises(
            AssetConsistencyError,
            match="thumbnail metadata exists without an object",
        ):
            assert_consistent_active_dataset(
                session,
                dataset_id=api_settings.dataset_id,
                active_root=active_root,
            )


def test_restore_database_override_changes_only_valid_postgres_database_name():
    source = "postgresql+psycopg://asset:p%40ss@postgres:5432/current"
    changed = _database_url_for_name(source, "c19_restore_20260711")
    assert changed.endswith("/c19_restore_20260711")
    assert "postgres:5432" in changed
    with pytest.raises(AssetConsistencyError):
        _database_url_for_name(source, 'bad"name')
    with pytest.raises(AssetConsistencyError):
        _database_url_for_name("sqlite:///asset.db", "restore_db")


def test_backup_drain_blocks_confirmed_and_unsettled_object_transitions(
    client, app, api_settings, service_headers
):
    response = client.post(
        "/v1/upload-intents",
        headers=service_headers,
        json=upload_payload(b"pending bytes", client_asset_id="drain-state"),
    )
    assert response.status_code == 201
    asset_id = response.json()["asset"]["asset_id"]

    # An unconfirmed pending upload may be omitted from the portable byte set.
    with app.state.database.session_factory() as session:
        assert backup_drain_blocker_count(
            session, dataset_id=api_settings.dataset_id
        ) == 0

    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        asset.status = "uploaded"
        session.commit()
    with app.state.database.session_factory() as session:
        assert backup_drain_blocker_count(
            session, dataset_id=api_settings.dataset_id
        ) == 1

    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        asset.status = "quarantined"
        # The still-present incoming key means the worker has not completed the
        # terminal move yet.
        session.commit()
    with app.state.database.session_factory() as session:
        assert backup_drain_blocker_count(
            session, dataset_id=api_settings.dataset_id
        ) == 1

    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        asset.incoming_object_key = None
        asset.quarantine_object_key = "11/22/" + "3" * 28
        session.commit()
    with app.state.database.session_factory() as session:
        assert backup_drain_blocker_count(
            session, dataset_id=api_settings.dataset_id
        ) == 0

    with app.state.database.session_factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        asset.status = "delete_pending"
        session.commit()
    with app.state.database.session_factory() as session:
        assert backup_drain_blocker_count(
            session, dataset_id=api_settings.dataset_id
        ) == 1


def test_drain_count_cli_is_read_only_and_does_not_require_active_mount(
    client, api_settings, monkeypatch, capsys
):
    del client
    monkeypatch.setenv("C19_ASSET_DATABASE_URL", api_settings.database_url)
    monkeypatch.setenv("C19_ASSET_DATASET_ID", api_settings.dataset_id)
    monkeypatch.delenv("C19_ASSET_ACTIVE_ROOT", raising=False)

    assert consistency_main(["--drain-blocker-count"]) == 0
    assert capsys.readouterr().out == "0\n"
