from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

from c19_asset_service.consistency import ManifestEntry, render_manifest


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv" / "bin" / "python"


def _private_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o600)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    generation = tmp_path / "generation-001"
    generation.mkdir(mode=0o700, parents=True)
    for name in ("barong", "record", "asset"):
        (generation / name).mkdir(mode=0o700)

    barong = generation / "barong" / "barong_ops_20260712T100000Z.dump"
    record = generation / "record" / "c19_records_20260712T100000Z.dump"
    asset_base = generation / "asset" / "c19_assets_20260712T100000Z"
    asset_database = Path(f"{asset_base}.dump")
    asset_objects = Path(f"{asset_base}.objects.tar")
    asset_manifest = Path(f"{asset_base}.manifest")
    asset_metadata = Path(f"{asset_base}.metadata")
    _private_write(barong, b"PGDMP\x01barong-control")
    _private_write(record, b"PGDMP\x01record-store")
    _private_write(asset_database, b"PGDMP\x01asset-store")

    object_name = "aa/bb/" + "c" * 28
    object_body = b"portable-asset-body"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        info = tarfile.TarInfo(object_name)
        info.size = len(object_body)
        info.mode = 0o600
        info.mtime = 0
        archive.addfile(info, io.BytesIO(object_body))
    _private_write(asset_objects, buffer.getvalue())
    object_digest = hashlib.sha256(object_body).hexdigest()
    _private_write(
        asset_manifest,
        render_manifest(
            {
                object_name: ManifestEntry(
                    sha256_hex=object_digest,
                    size_bytes=len(object_body),
                    object_key=object_name,
                )
            }
        ).encode(),
    )

    _private_write(
        Path(f"{barong}.metadata"),
        (
            "created_at=20260712T100000Z\n"
            "source_dataset_id=barong-control-test\n"
            "app_version=stage6-test\n"
            "alembic_revision=barong_revision_001\n"
            "database_url=postgresql://test:[redacted]@db/control\n"
            "format=pg_dump_custom\n"
            f"archive={barong}\n"
            f"archive_sha256={_sha(barong)}\n"
        ).encode(),
    )
    _private_write(
        Path(f"{record}.metadata"),
        (
            "created_at=20260712T100000Z\n"
            "source_dataset_id=record-test\n"
            "alembic_revision=c19_record_20260712_04\n"
            "format=pg_dump_custom\n"
            f"archive_sha256={_sha(record)}\n"
        ).encode(),
    )
    _private_write(
        asset_metadata,
        (
            "created_at=20260712T100000Z\n"
            "source_dataset_id=asset-test\n"
            "alembic_revision=c19_asset_20260712_03\n"
            "blob_format_revision=1\n"
            "database_format=pg_dump_custom\n"
            "object_archive_format=posix_tar\n"
            "object_count=1\n"
            f"object_bytes={len(object_body)}\n"
            f"database_sha256={_sha(asset_database)}\n"
            f"objects_sha256={_sha(asset_objects)}\n"
            f"manifest_sha256={_sha(asset_manifest)}\n"
        ).encode(),
    )
    key = tmp_path / "manifest.key"
    _private_write(key, b"stage6-test-hmac-key-" + b"x" * 48)
    manifest = generation / "c19-full-generation-001.json"

    seal = subprocess.run(
        [
            str(PYTHON),
            "scripts/c19_full_dr.py",
            "seal",
            "--generation-dir",
            str(generation),
            "--generation-id",
            "generation-001",
            "--barong-dataset-id",
            "barong-control-test",
            "--record-dataset-id",
            "record-test",
            "--asset-dataset-id",
            "asset-test",
            "--barong-archive",
            str(barong),
            "--record-archive",
            str(record),
            "--asset-metadata",
            str(asset_metadata),
            "--quiesced-at",
            "20260712T095959Z",
            "--captured-at",
            "20260712T100001Z",
            "--manifest",
            str(manifest),
            "--hmac-key-file",
            str(key),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert seal.returncode == 0, seal.stderr
    return manifest, key


def _verify(manifest: Path, key: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(PYTHON),
            "scripts/c19_full_dr.py",
            "verify",
            "--manifest",
            str(manifest),
            "--hmac-key-file",
            str(key),
            "--expected-barong-dataset",
            "barong-control-test",
            "--expected-record-dataset",
            "record-test",
            "--expected-asset-dataset",
            "asset-test",
            *extra,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_full_bundle_seal_verify_and_restore_admission_are_content_free(tmp_path: Path) -> None:
    manifest, key = _fixture(tmp_path)
    verified = _verify(
        manifest,
        key,
        "--expected-record-revision",
        "c19_record_20260712_04",
        "--expected-asset-revision",
        "c19_asset_20260712_03",
    )
    assert verified.returncode == 0, verified.stderr
    assert "bundle verification passed" in verified.stdout.lower()
    assert "portable-asset-body" not in verified.stdout

    admitted = subprocess.run(
        [
            "bash",
            "scripts/c19_full_restore_verify.sh",
            "--manifest",
            str(manifest),
            "--hmac-key-file",
            str(key),
            "--barong-dataset-id",
            "barong-control-test",
            "--record-dataset-id",
            "record-test",
            "--asset-dataset-id",
            "asset-test",
            "--barong-revision",
            "barong_revision_001",
            "--record-revision",
            "c19_record_20260712_04",
            "--asset-revision",
            "c19_asset_20260712_03",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert admitted.returncode == 0, admitted.stderr
    assert "no restore" in admitted.stdout.lower()
    assert "required_manual_restore_confirmation: RESTORE/" in admitted.stdout


def test_full_bundle_rejects_tampering_wrong_identity_and_automatic_restore(
    tmp_path: Path,
) -> None:
    manifest, key = _fixture(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    record = manifest.parent / document["artifacts"]["record_archive"]["path"]
    os.chmod(record, 0o600)
    record.write_bytes(record.read_bytes() + b"tampered")
    tampered = _verify(manifest, key)
    assert tampered.returncode == 1
    assert "differs from the sealed manifest" in tampered.stderr

    manifest, key = _fixture(tmp_path / "second")
    wrong = _verify(manifest, key, "--expected-record-dataset", "other-record")
    assert wrong.returncode == 1
    assert "does not match the restore target" in wrong.stderr

    blocked = subprocess.run(
        ["bash", "scripts/c19_full_restore_verify.sh", "--execute"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert blocked.returncode == 1
    assert "intentionally unsupported" in blocked.stderr


def test_full_backup_dry_run_never_touches_docker_and_coordinator_is_fail_closed(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            "bash",
            "scripts/c19_full_backup.sh",
            "--dry-run",
            "--generation-id",
            "generation-dry-run",
            "--output-dir",
            str(tmp_path / "must-not-exist"),
            "--barong-dataset-id",
            "barong-control-test",
            "--record-dataset-id",
            "record-test",
            "--asset-dataset-id",
            "asset-test",
        ],
        cwd=ROOT,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "No containers, databases, volumes, or files were changed." in result.stdout
    assert not (tmp_path / "must-not-exist").exists()

    coordinator = (ROOT / "scripts/c19_full_backup.sh").read_text(encoding="utf-8")
    assert 'mode="dry-run"' in coordinator
    assert "CONFIRM_C19_FULL_BACKUP" in coordinator
    assert "flock -n 8" in coordinator
    assert "--leave-stopped" in coordinator
    assert "c19_full_dr.py seal" in coordinator
    assert "c19_full_dr.py verify" in coordinator
    for retention_table in (
        "record_asset_coordination",
        "record_asset_deletion_outbox",
        "record_retention_operations",
        "record_retention_batches",
    ):
        assert retention_table in coordinator
    for record_schema_object in (
        "pk_record_asset_coordination",
        "pk_record_asset_deletion_outbox",
        "pk_record_retention_operations",
        "pk_record_retention_batches",
        "fk_record_asset_deletion_outbox_retention_operation_id__ecb1",
        "fk_record_retention_batches_operation_id_record_retenti_0030",
        "uq_record_asset_deletion_outbox_record_asset",
        "ck_record_asset_deletion_outbox_state_supported",
        "ck_record_asset_deletion_outbox_lease_pair_consistent",
        "ck_record_asset_deletion_outbox_completion_consistent",
        "ck_record_asset_deletion_outbox_authorization_consistent",
        "ck_record_retention_operations_approved_maximum_supported",
        "ck_record_retention_operations_approved_asset_maximum_supported",
        "ck_record_retention_operations_asset_jobs_enqueued_with_3d91",
        "ck_record_retention_operations_asset_jobs_completed_wit_5f0c",
        "ck_record_retention_operations_affected_within_approved_maximum",
        "ck_record_retention_batches_cumulative_count_consistent",
        "ix_record_asset_deletion_outbox_state_created",
        "ix_record_asset_deletion_outbox_retention_operation",
        "ix_record_asset_deletion_outbox_asset_state",
        "ix_record_asset_deletion_outbox_lease_until",
        "ix_record_asset_deletion_outbox_authorized_at",
        "ix_record_retention_operations_completed_at",
    ):
        assert record_schema_object in coordinator
    for source_catalog_gate in (
        "validate_record_source_catalog",
        "information_schema.columns",
        "constraint_record.convalidated",
        "constraint_record.contype",
        "constraint_record.confrelid",
        "constraint_record.conkey[1]",
        "constraint_record.confkey[1]",
        "constraint_record.confdeltype",
        "index_state.indisvalid",
        "index_state.indisready",
        "Frozen Record v4 source is missing required column",
        "Frozen Record v4 source has an invalid foreign key",
    ):
        assert source_catalog_gate in coordinator
    assert "retention_operation_id:record_retention_operations:operation_id:r" in coordinator
    assert "operation_id:record_retention_operations:operation_id:r" in coordinator
    for retention_schema_object in (
        "retention_operation_id",
        "retention_record_id",
        "retention_conversation_id",
        "retention_prepared_at",
        "ck_chat_assets_retention_preparation_consistent",
        "uq_chat_assets_retention_operation_id",
        "ix_chat_assets_retention_prepared_at",
    ):
        assert retention_schema_object in coordinator
    admission = (ROOT / "scripts/c19_full_restore_verify.sh").read_text(
        encoding="utf-8"
    )
    assert "c19_record_20260712_04" in admission
    assert "c19_asset_20260712_03" in admission
    assert "docker-compose down" not in coordinator
    assert " down " not in coordinator


def test_barong_backup_accepts_sqlalchemy_psycopg_url_without_exposing_credentials(
    tmp_path: Path,
) -> None:
    password = "stage6-secret-password"
    result = subprocess.run(
        [
            "bash",
            "scripts/pg_backup.sh",
            "--dry-run",
            "--database-url",
            f"postgresql+psycopg://barong:{password}@db:5432/barong_test",
            "--output-dir",
            str(tmp_path / "must-not-exist"),
            "--app-version",
            "stage6-test",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "postgresql://[redacted]@db:5432/barong_test" in result.stdout
    assert password not in result.stdout
    assert password not in result.stderr
    assert not (tmp_path / "must-not-exist").exists()
