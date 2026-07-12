from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

RECORD_TABLES = (
    "alembic_version",
    "chat_participant_positions",
    "chat_records",
    "chat_user_record_events",
    "moment_asset_references",
    "moment_audience_snapshots",
    "moment_comments",
    "moment_feed_sequence",
    "moment_likes",
    "moment_user_events",
    "moments",
    "record_asset_coordination",
    "record_asset_deletion_outbox",
    "record_asset_references",
    "record_conversation_sequences",
    "record_idempotency_ledger",
    "record_mutation_audits",
    "record_retention_batches",
    "record_retention_operations",
    "record_user_event_sequences",
)

RECORD_COLUMNS = {
    "record_idempotency_ledger": (
        "sender_user_id",
        "client_message_id",
        "intent_sha256",
        "intent_version",
        "record_id",
        "status",
        "deleted_at",
    ),
    "record_asset_references": (
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
    ),
    "record_asset_coordination": ("asset_id", "created_at"),
    "moments": (
        "id",
        "client_moment_id",
        "author_user_id",
        "author_org_id",
        "state",
        "visibility",
        "audience_org_ids",
        "content",
        "feed_sequence",
        "like_count",
        "comment_count",
        "publish_intent_sha256",
        "created_at",
        "persisted_at",
        "published_at",
        "delete_pending_at",
        "deleted_at",
    ),
    "moment_asset_references": (
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
    ),
    "moment_user_events": (
        "user_id",
        "event_sequence",
        "event_type",
        "moment_id",
        "actor_user_id",
        "comment_id",
        "created_at",
    ),
    "record_retention_operations": (
        "operation_id",
        "requested_by_user_id",
        "reason",
        "delete_before",
        "conversation_id",
        "approved_maximum_records",
        "approved_maximum_asset_jobs",
        "affected_count",
        "asset_jobs_enqueued_count",
        "asset_jobs_completed_count",
        "next_batch_ordinal",
        "created_at",
        "updated_at",
        "completed_at",
    ),
    "record_retention_batches": (
        "operation_id",
        "batch_ordinal",
        "maximum_records",
        "affected_count",
        "cumulative_affected_count",
        "operation_complete",
        "completed_at",
    ),
    "record_asset_deletion_outbox": (
        "id",
        "asset_id",
        "record_id",
        "conversation_id",
        "retention_operation_id",
        "state",
        "attempt_count",
        "created_at",
        "last_attempt_at",
        "authorized_at",
        "lease_owner",
        "lease_until",
        "outcome",
        "completed_at",
    ),
}

RECORD_CONSTRAINTS = (
    "record_asset_coordination:pk_record_asset_coordination:p",
    "record_asset_deletion_outbox:pk_record_asset_deletion_outbox:p",
    "record_retention_operations:pk_record_retention_operations:p",
    "record_retention_batches:pk_record_retention_batches:p",
    "record_asset_deletion_outbox:fk_record_asset_deletion_outbox_retention_operation_id__ecb1:f",
    "record_retention_batches:fk_record_retention_batches_operation_id_record_retenti_0030:f",
    "record_asset_deletion_outbox:uq_record_asset_deletion_outbox_record_asset:u",
    "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_attempt_count_nonnegative:c",
    "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_state_supported:c",
    "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_outcome_supported:c",
    "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_lease_pair_consistent:c",
    "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_completion_consistent:c",
    "record_asset_deletion_outbox:ck_record_asset_deletion_outbox_authorization_consistent:c",
    "record_retention_operations:ck_record_retention_operations_approved_maximum_supported:c",
    "record_retention_operations:ck_record_retention_operations_approved_asset_maximum_supported:c",
    "record_retention_operations:ck_record_retention_operations_asset_jobs_enqueued_with_3d91:c",
    "record_retention_operations:ck_record_retention_operations_asset_jobs_completed_wit_5f0c:c",
    "record_retention_operations:ck_record_retention_operations_affected_count_nonnegative:c",
    "record_retention_operations:ck_record_retention_operations_affected_within_approved_maximum:c",
    "record_retention_operations:ck_record_retention_operations_next_batch_ordinal_nonnegative:c",
    "record_retention_batches:ck_record_retention_batches_batch_ordinal_nonnegative:c",
    "record_retention_batches:ck_record_retention_batches_maximum_records_supported:c",
    "record_retention_batches:ck_record_retention_batches_affected_within_batch_maximum:c",
    "record_retention_batches:ck_record_retention_batches_cumulative_count_consistent:c",
)

RECORD_FOREIGN_KEYS = (
    "record_asset_deletion_outbox:fk_record_asset_deletion_outbox_retention_operation_id__ecb1:retention_operation_id:record_retention_operations:operation_id:r",
    "record_retention_batches:fk_record_retention_batches_operation_id_record_retenti_0030:operation_id:record_retention_operations:operation_id:r",
)

RECORD_INDEXES = (
    "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_state_created",
    "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_retention_operation",
    "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_asset_state",
    "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_lease_until",
    "record_asset_deletion_outbox:ix_record_asset_deletion_outbox_authorized_at",
    "record_retention_operations:ix_record_retention_operations_completed_at",
)

ASSET_COLUMNS = (
    "retention_operation_id",
    "retention_record_id",
    "retention_conversation_id",
    "retention_prepared_at",
)
ASSET_CONSTRAINTS = (
    "chat_assets:ck_chat_assets_retention_preparation_consistent:c",
    "chat_assets:uq_chat_assets_retention_operation_id:u",
)
ASSET_INDEXES = ("chat_assets:ix_chat_assets_retention_prepared_at",)


FAKE_RUNTIME = r'''#!/usr/bin/env python3
import json
import os
import pathlib
import sys

config = json.loads(pathlib.Path(os.environ["FAKE_CONFIG"]).read_text())
args = sys.argv[1:]
joined = " ".join(args)
with pathlib.Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as log:
    log.write(pathlib.Path(sys.argv[0]).name + " " + joined + "\n")

def emit(value="", code=0):
    if value:
        sys.stdout.write(str(value))
        if not str(value).endswith("\n"):
            sys.stdout.write("\n")
    raise SystemExit(code)

service = os.environ["FAKE_SERVICE"]
workflow = os.environ["FAKE_WORKFLOW"]
failure = os.environ["FAKE_FAILURE"]
dataset = os.environ["FAKE_DATASET"]
database = os.environ["FAKE_DATABASE"]
user = os.environ["FAKE_USER"]

if pathlib.Path(sys.argv[0]).name == "docker":
    if args[:2] == ["volume", "inspect"]:
        if "--format" not in args:
            emit()
        volume = args[-1]
        if service == "record":
            emit(dataset)
        role = "metadata"
        for candidate in ("incoming", "quarantine", "active"):
            if candidate in volume:
                role = candidate
        emit(dataset + "\t" + role)
    if args and args[0] == "inspect":
        fmt = args[args.index("--format") + 1]
        container = args[-1]
        if ".Mounts" in fmt:
            if service == "record" or "postgres" in container:
                emit("volume\t" + os.environ["FAKE_POSTGRES_VOLUME"])
            emit("volume\t" + os.environ["FAKE_ACTIVE_VOLUME"])
        if ".Config.Env" in fmt:
            emit(
                "POSTGRES_DB=" + database + "\n"
                "POSTGRES_USER=" + user + "\n"
                "C19_RECORD_DATASET_ID=" + dataset
            )
        if ".State.Running" in fmt:
            emit("true")
        if ".State.Status" in fmt:
            emit("running")
        if ".State.Health" in fmt:
            emit("healthy")
    emit()

tokens = list(args)
while tokens and tokens[0] in {"-p", "-f", "--env-file"}:
    tokens = tokens[2:]
if not tokens:
    emit()
action = tokens[0]

if action == "ps" and "-q" in tokens:
    target = tokens[-1]
    if workflow == "restore" and service == "asset" and target in {
        "c19-asset-api", "c19-asset-worker", "c19-asset-gateway"
    }:
        emit()
    emit("fake-" + target)

if "pg_restore --list" in joined:
    emit("\n".join(
        f"1; 0 0 TABLE public {table_name} owner"
        for table_name in config["record_tables"]
    ))
if "pg_restore" in joined:
    emit()
if "pg_isready" in joined:
    emit()
if "--drain-blocker-count" in joined:
    emit("0")
if 'printf "%s\\t%s\\t%s"' in joined:
    emit(database + "\t" + user + "\t" + dataset)
if "select version_num from alembic_version" in joined:
    emit(
        "c19_record_20260712_04"
        if service == "record"
        else "c19_asset_20260712_03"
    )
if "to_regclass" in joined:
    emit("true" if service == "record" and workflow == "backup" else "false")
if "information_schema.columns" in joined:
    if service == "asset":
        emit("\n".join(config["asset_columns"]))
    if "table_name || ':' || column_name" in joined:
        emit("\n".join(
            table_name + ":" + column
            for table_name, columns in config["record_columns"].items()
            for column in columns
        ))
    for table_name, columns in config["record_columns"].items():
        if f"table_name = '{table_name}'" in joined:
            emit("\n".join(columns))
    emit()
if "constraint_record.confrelid" in joined:
    emit("\n".join(config["record_foreign_keys"]))
if "pg_constraint" in joined:
    values = list(
        config["record_constraints"]
        if service == "record"
        else config["asset_constraints"]
    )
    if failure == "missing_constraint":
        needle = (
            "authorization_consistent"
            if service == "record"
            else "retention_preparation_consistent"
        )
        values = [value for value in values if needle not in value]
    emit("\n".join(values))
if "pg_index" in joined:
    values = list(
        config["record_indexes"]
        if service == "record"
        else config["asset_indexes"]
    )
    if failure == "invalid_index":
        needle = "authorized_at" if service == "record" else "retention_prepared_at"
        values = [value for value in values if needle not in value]
    emit("\n".join(values))
if "pg_dump" in joined:
    emit("PGDMP-should-not-be-reached")
if action in {"exec", "run", "up", "start", "stop"}:
    emit()
emit()
'''


def _fake_runtime(
    tmp_path: Path,
    *,
    service: str,
    workflow: str,
    failure: str,
    dataset: str,
    database: str,
    user: str,
    postgres_volume: str,
    active_volume: str = "unused-active",
) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    dispatcher = fake_bin / "dispatcher"
    dispatcher.write_text(FAKE_RUNTIME, encoding="utf-8")
    dispatcher.chmod(0o755)
    (fake_bin / "docker").symlink_to(dispatcher)
    (fake_bin / "docker-compose").symlink_to(dispatcher)
    config = tmp_path / "fake-config.json"
    config.write_text(
        json.dumps(
            {
                "record_tables": RECORD_TABLES,
                "record_columns": RECORD_COLUMNS,
                "record_constraints": RECORD_CONSTRAINTS,
                "record_foreign_keys": RECORD_FOREIGN_KEYS,
                "record_indexes": RECORD_INDEXES,
                "asset_columns": ASSET_COLUMNS,
                "asset_constraints": ASSET_CONSTRAINTS,
                "asset_indexes": ASSET_INDEXES,
            }
        ),
        encoding="utf-8",
    )
    log = tmp_path / "fake-runtime.log"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "FAKE_CONFIG": str(config),
        "FAKE_LOG": str(log),
        "FAKE_SERVICE": service,
        "FAKE_WORKFLOW": workflow,
        "FAKE_FAILURE": failure,
        "FAKE_DATASET": dataset,
        "FAKE_DATABASE": database,
        "FAKE_USER": user,
        "FAKE_POSTGRES_VOLUME": postgres_volume,
        "FAKE_ACTIVE_VOLUME": active_volume,
    }
    return environment, log


def _record_env(tmp_path: Path) -> Path:
    password = "p" * 40
    path = tmp_path / "record.env"
    path.write_text(
        "\n".join(
            (
                "C19_RECORD_DATASET_ID=record-schema-test",
                "POSTGRES_DB=c19_chat_records",
                "POSTGRES_USER=c19_record_service",
                f"POSTGRES_PASSWORD={password}",
                "C19_RECORD_DATABASE_URL="
                f"postgresql+psycopg://c19_record_service:{password}"
                "@c19-record-postgres:5432/c19_chat_records",
                f"C19_RECORD_SERVICE_TOKEN={'s' * 40}",
                f"C19_RECORD_CURSOR_SIGNING_SECRET={'c' * 40}",
                "C19_RECORD_CURSOR_TTL_SECONDS=900",
                "C19_RECORD_MAX_MESSAGE_CHARS=4000",
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


def _asset_env(tmp_path: Path) -> Path:
    password = "a" * 40
    path = tmp_path / "asset.env"
    path.write_text(
        "\n".join(
            (
                "C19_ASSET_DATASET_ID=asset-schema-test",
                "POSTGRES_DB=c19_chat_assets",
                "POSTGRES_USER=c19_asset_service",
                f"POSTGRES_PASSWORD={password}",
                "C19_ASSET_DATABASE_URL="
                f"postgresql+psycopg://c19_asset_service:{password}"
                "@c19-asset-postgres:5432/c19_chat_assets",
                f"C19_ASSET_SERVICE_TOKEN={'s' * 40}",
                f"C19_ASSET_GATEWAY_TOKEN={'g' * 40}",
                "C19_ASSET_INCOMING_ROOT=/var/lib/c19-assets/incoming",
                "C19_ASSET_QUARANTINE_ROOT=/var/lib/c19-assets/quarantine",
                "C19_ASSET_ACTIVE_ROOT=/var/lib/c19-assets/active",
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


def _record_archive(tmp_path: Path) -> Path:
    archive = tmp_path / "c19_records.dump"
    archive.write_bytes(b"synthetic-record-archive")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    Path(f"{archive}.metadata").write_text(
        "\n".join(
            (
                "created_at=20260712T000000Z",
                "source_dataset_id=record-schema-test",
                "alembic_revision=c19_record_20260712_04",
                "format=pg_dump_custom",
                f"archive_sha256={digest}",
                "",
            )
        ),
        encoding="utf-8",
    )
    return archive


def _asset_archive(tmp_path: Path) -> Path:
    base = tmp_path / "c19_assets_20260712T000000Z"
    dump = Path(f"{base}.dump")
    objects = Path(f"{base}.objects.tar")
    manifest = Path(f"{base}.manifest")
    metadata = Path(f"{base}.metadata")
    dump.write_bytes(b"synthetic-asset-archive")
    object_name = "aa/bb/" + "c" * 28
    body = b"asset-body"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        info = tarfile.TarInfo(object_name)
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
    objects.write_bytes(buffer.getvalue())
    manifest.write_text(
        f"{hashlib.sha256(body).hexdigest()}\t{len(body)}\t{object_name}\n",
        encoding="utf-8",
    )
    metadata.write_text(
        "\n".join(
            (
                "created_at=20260712T000000Z",
                "source_dataset_id=asset-schema-test",
                "alembic_revision=c19_asset_20260712_03",
                "blob_format_revision=1",
                "database_format=pg_dump_custom",
                "object_archive_format=posix_tar",
                "object_count=1",
                f"object_bytes={len(body)}",
                f"database_sha256={hashlib.sha256(dump.read_bytes()).hexdigest()}",
                f"objects_sha256={hashlib.sha256(objects.read_bytes()).hexdigest()}",
                f"manifest_sha256={hashlib.sha256(manifest.read_bytes()).hexdigest()}",
                "",
            )
        ),
        encoding="utf-8",
    )
    return metadata


def test_record_backup_rejects_missing_validated_constraint_before_pg_dump(
    tmp_path: Path,
) -> None:
    env_file = _record_env(tmp_path)
    environment, log = _fake_runtime(
        tmp_path,
        service="record",
        workflow="backup",
        failure="missing_constraint",
        dataset="record-schema-test",
        database="c19_chat_records",
        user="c19_record_service",
        postgres_volume="record_schema_volume",
    )
    environment.update(
        {
            "C19_RECORD_ENV_FILE": str(env_file),
            "C19_RECORD_VOLUME_NAME": "record_schema_volume",
            "C19_RECORD_BACKUP_DIR": str(tmp_path / "backups"),
            "C19_RECORD_LOCK_DIR": str(tmp_path / "locks"),
        }
    )

    result = subprocess.run(
        ["bash", "scripts/c19_record_backup.sh"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "missing validated constraint" in result.stderr
    assert "pg_dump" not in log.read_text(encoding="utf-8")


def test_record_restore_rejects_invalid_index_before_database_swap(
    tmp_path: Path,
) -> None:
    env_file = _record_env(tmp_path)
    archive = _record_archive(tmp_path)
    environment, log = _fake_runtime(
        tmp_path,
        service="record",
        workflow="restore",
        failure="invalid_index",
        dataset="record-schema-test",
        database="c19_chat_records",
        user="c19_record_service",
        postgres_volume="record_restore_volume",
    )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    environment.update(
        {
            "C19_RECORD_ENV_FILE": str(env_file),
            "C19_RECORD_COMPOSE_PROJECT": "c19-record-restore",
            "C19_RECORD_VOLUME_NAME": "record_restore_volume",
            "C19_RECORD_PRIVATE_NETWORK_NAME": "record-restore-private",
            "BARONG_SHARED_NETWORK_NAME": "record-restore-client",
            "C19_RECORD_LOCK_DIR": str(tmp_path / "locks"),
            "CONFIRM_C19_RECORD_RESTORE": (
                "record-schema-test/"
                f"{digest}/c19-record-restore/c19_chat_records/"
                "record_restore_volume/record-restore-private/record-restore-client"
            ),
        }
    )

    result = subprocess.run(
        [
            "bash",
            "scripts/c19_record_restore.sh",
            "--archive",
            str(archive),
            "--execute",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "missing ready index" in result.stderr
    assert "alter database" not in log.read_text(encoding="utf-8").lower()


def test_asset_backup_rejects_missing_validated_constraint_before_pg_dump(
    tmp_path: Path,
) -> None:
    env_file = _asset_env(tmp_path)
    environment, log = _fake_runtime(
        tmp_path,
        service="asset",
        workflow="backup",
        failure="missing_constraint",
        dataset="asset-schema-test",
        database="c19_chat_assets",
        user="c19_asset_service",
        postgres_volume="asset_schema_postgres",
        active_volume="asset_schema_active",
    )
    environment.update(
        {
            "C19_ASSET_ENV_FILE": str(env_file),
            "C19_ASSET_POSTGRES_VOLUME_NAME": "asset_schema_postgres",
            "C19_ASSET_INCOMING_VOLUME_NAME": "asset_schema_incoming",
            "C19_ASSET_QUARANTINE_VOLUME_NAME": "asset_schema_quarantine",
            "C19_ASSET_ACTIVE_VOLUME_NAME": "asset_schema_active",
            "C19_ASSET_BACKUP_DIR": str(tmp_path / "backups"),
        }
    )

    result = subprocess.run(
        ["bash", "scripts/c19_asset_backup.sh", "--execute"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "missing validated constraint" in result.stderr
    assert "pg_dump" not in log.read_text(encoding="utf-8")


def test_asset_restore_rejects_invalid_index_before_database_swap(
    tmp_path: Path,
) -> None:
    env_file = _asset_env(tmp_path)
    metadata = _asset_archive(tmp_path)
    base = metadata.with_suffix("")
    dump = Path(f"{base}.dump")
    objects = Path(f"{base}.objects.tar")
    environment, log = _fake_runtime(
        tmp_path,
        service="asset",
        workflow="restore",
        failure="invalid_index",
        dataset="asset-schema-test",
        database="c19_chat_assets",
        user="c19_asset_service",
        postgres_volume="asset_restore_postgres",
        active_volume="asset_restore_active",
    )
    environment.update(
        {
            "C19_ASSET_ENV_FILE": str(env_file),
            "C19_ASSET_COMPOSE_PROJECT": "c19-asset-restore",
            "C19_ASSET_POSTGRES_VOLUME_NAME": "asset_restore_postgres",
            "C19_ASSET_INCOMING_VOLUME_NAME": "asset_restore_incoming",
            "C19_ASSET_QUARANTINE_VOLUME_NAME": "asset_restore_quarantine",
            "C19_ASSET_ACTIVE_VOLUME_NAME": "asset_restore_active",
            "C19_ASSET_PRIVATE_NETWORK_NAME": "asset-restore-private",
            "C19_ASSET_CLAM_EGRESS_NETWORK_NAME": "asset-restore-clam-egress",
            "C19_ASSET_GATEWAY_INGRESS_NETWORK_NAME": "asset-restore-gateway-ingress",
            "BARONG_SHARED_NETWORK_NAME": "asset-restore-client",
            "C19_ASSET_LOCK_DIR": str(tmp_path / "locks"),
            "CONFIRM_C19_ASSET_RESTORE": (
                "asset-schema-test/"
                f"{hashlib.sha256(dump.read_bytes()).hexdigest()}/"
                f"{hashlib.sha256(objects.read_bytes()).hexdigest()}/"
                "c19-asset-restore/c19_chat_assets/asset_restore_postgres/"
                "asset_restore_active/asset-restore-private/"
                "asset-restore-clam-egress/asset-restore-gateway-ingress/"
                "asset-restore-client"
            ),
        }
    )

    result = subprocess.run(
        [
            "bash",
            "scripts/c19_asset_restore.sh",
            "--metadata",
            str(metadata),
            "--execute",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "missing index" in result.stderr
    assert "alter database" not in log.read_text(encoding="utf-8").lower()
