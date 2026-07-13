from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _service_block(document: str, service_name: str) -> str:
    marker = f"  {service_name}:\n"
    match = re.search(rf"(?m)^{re.escape(marker)}", document)
    if match is None:
        raise AssertionError(f"service is missing: {service_name}")
    start = match.end()
    end = len(document)
    offset = start
    for line in document[start:].splitlines(keepends=True):
        if line.startswith("  ") and not line.startswith("    "):
            end = offset
            break
        offset += len(line)
    return document[start:end]


def test_asset_stack_separates_control_bytes_scanner_and_volumes() -> None:
    document = (ROOT / "docker-compose.c19-asset.yml").read_text(encoding="utf-8")
    database = _service_block(document, "c19-asset-postgres")
    api = _service_block(document, "c19-asset-api")
    volume_init = _service_block(document, "c19-asset-volume-init")
    worker = _service_block(document, "c19-asset-worker")
    gateway = _service_block(document, "c19-asset-gateway")
    clamd = _service_block(document, "c19-asset-clamd")

    assert "    ports:" not in database
    assert "    ports:" not in api
    assert "    ports:" not in worker
    assert "    ports:" not in clamd
    assert '      - "127.0.0.1:${C19_ASSET_GATEWAY_HOST_PORT:-8092}:8092"' in gateway

    assert "      - c19-asset-private" in database
    assert "      - barong-ops-console-prod" not in database
    assert "      - c19-asset-private" in api
    assert "      - barong-ops-console-prod" in api
    assert "      - barong-ops-console-prod" not in worker
    assert "      - barong-ops-console-prod" not in gateway
    assert "      - barong-ops-console-prod" not in clamd
    assert "    internal: true" in document
    assert "      - c19-asset-clam-egress" in clamd
    assert "      - c19-asset-gateway-ingress" in gateway
    for service in (database, api, worker, gateway):
        assert "      - c19-asset-clam-egress" not in service
    for service in (database, api, worker, clamd):
        assert "      - c19-asset-gateway-ingress" not in service
    assert "C19_ASSET_CLAM_EGRESS_NETWORK_NAME" in document
    assert "C19_ASSET_GATEWAY_INGRESS_NETWORK_NAME" in document
    assert "com.barong.c19.asset-network-role: malware-signature-egress" in document
    assert "com.barong.c19.asset-network-role: host-loopback-ingress" in document
    assert 'com.docker.network.bridge.enable_ip_masquerade: "false"' in document

    assert "/var/lib/c19-assets/active" not in api
    assert "/var/lib/c19-assets/incoming" not in api
    assert "/var/lib/c19-assets/quarantine" not in api
    assert "c19_asset_incoming_data:/var/lib/c19-assets/incoming" in worker
    assert "c19_asset_quarantine_data:/var/lib/c19-assets/quarantine" in worker
    assert "c19_asset_active_data:/var/lib/c19-assets/active" in worker
    assert "c19_asset_active_data:/var/lib/c19-assets/active:ro" in gateway
    assert '      C19_ASSET_DATABASE_URL: ""' in gateway
    assert '      C19_ASSET_SERVICE_TOKEN: ""' in gateway
    assert '      POSTGRES_PASSWORD: ""' in gateway
    assert '      C19_ASSET_GATEWAY_TOKEN: ""' in worker

    assert '    user: "0:0"' in volume_init
    assert '    restart: "no"' in volume_init
    assert "chown -R 10001:10001" in volume_init
    assert '    network_mode: "none"' in volume_init
    assert "condition: service_completed_successfully" in worker
    assert "    stop_grace_period: 180s" in worker
    dockerfile = (ROOT / "c19_asset_service/Dockerfile").read_text(encoding="utf-8")
    assert "--gid 10001 c19asset" in dockerfile
    assert "--uid 10001 --gid 10001" in dockerfile
    assert "USER c19asset" in dockerfile

    assert "clamav/clamav:1.4" in clamd
    assert "    mem_limit: 4g" in clamd
    assert "    pids_limit: 128" in clamd
    assert '        max-size: "25m"' in clamd
    assert "./deploy/clamav/c19-clamd.conf:/etc/clamav/clamd.conf:ro" in clamd
    scanner_policy = (ROOT / "deploy/clamav/c19-clamd.conf").read_text(
        encoding="utf-8"
    )
    assert "User clamav" in scanner_policy
    assert "TCPSocket 3310" in scanner_policy
    assert "LocalSocket /run/clamav/clamd.sock" in scanner_policy
    assert "StreamMaxLength 64M" in scanner_policy
    assert "MaxFileSize 64M" in scanner_policy
    assert "ConcurrentDatabaseReload no" in scanner_policy
    assert "C19_ASSET_DATASET_ID:?C19_ASSET_DATASET_ID is required" in document
    for role in ("metadata", "incoming", "quarantine", "active"):
        assert f"com.barong.c19.asset-volume-role: {role}" in document


def test_compose_v1_renders_clam_limits_and_single_egress_owner() -> None:
    compose = shutil.which("docker-compose")
    if compose is None:
        pytest.skip("docker-compose v1 is unavailable")
    environment = os.environ.copy()
    environment.update(
        {
            "C19_ASSET_ENV_FILE": ".env.c19-asset.production.example",
            "C19_ASSET_DATASET_ID": "barong-c19-assets-compose-test",
            "C19_ASSET_PRIVATE_NETWORK_NAME": "c19-asset-compose-private",
            "C19_ASSET_CLAM_EGRESS_NETWORK_NAME": "c19-asset-compose-clam-egress",
            "C19_ASSET_GATEWAY_INGRESS_NETWORK_NAME": "c19-asset-compose-gateway-ingress",
            "BARONG_SHARED_NETWORK_NAME": "c19-asset-compose-client",
            "C19_ASSET_POSTGRES_VOLUME_NAME": "c19_asset_compose_postgres",
            "C19_ASSET_INCOMING_VOLUME_NAME": "c19_asset_compose_incoming",
            "C19_ASSET_QUARANTINE_VOLUME_NAME": "c19_asset_compose_quarantine",
            "C19_ASSET_ACTIVE_VOLUME_NAME": "c19_asset_compose_active",
            "C19_ASSET_CLAM_VOLUME_NAME": "c19_asset_compose_clam",
            "C19_ASSET_GATEWAY_HOST_PORT": "18092",
        }
    )
    result = subprocess.run(
        [
            compose,
            "-p",
            "c19-asset-compose-test",
            "-f",
            "docker-compose.c19-asset.yml",
            "config",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    clamd = _service_block(result.stdout, "c19-asset-clamd")
    assert "    mem_limit: 4g" in clamd
    assert "    pids_limit: 128" in clamd
    assert "      c19-asset-clam-egress: null" in clamd
    gateway = _service_block(result.stdout, "c19-asset-gateway")
    assert "      c19-asset-gateway-ingress: null" in gateway
    assert 'com.docker.network.bridge.enable_ip_masquerade: "false"' in result.stdout
    for service_name in (
        "c19-asset-postgres",
        "c19-asset-api",
        "c19-asset-worker",
        "c19-asset-gateway",
    ):
        assert "c19-asset-clam-egress" not in _service_block(
            result.stdout, service_name
        )


def test_barong_asset_credentials_are_available_only_to_backend() -> None:
    document = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
    backend = _service_block(document, "console_backend")
    assert "      - .env.production" in backend
    assert "C19_ASSET_STORE_TOKEN" not in backend

    for service_name in (
        "console_postgres",
        "r-w-worker",
        "r-a-worker",
        "k-worker",
        "key-health-worker",
        "console_frontend",
    ):
        service = _service_block(document, service_name)
        assert '      C19_ASSET_STORE_URL: ""' in service
        assert '      C19_ASSET_STORE_TOKEN: ""' in service
        assert '      C19_ASSET_STORE_TIMEOUT_SECONDS: ""' in service


def test_nginx_has_only_opaque_streaming_routes_with_per_request_auth() -> None:
    document = (ROOT / "deploy/nginx/ops.barongyekhna.com.conf.template").read_text(
        encoding="utf-8"
    )

    def location_body(marker: str) -> str:
        assert marker in document
        return document.split(marker, 1)[1].split("\n    }", 1)[0]

    sse = location_body("location = /api/backend/c19/events {")
    moment_sse = location_body("location = /api/backend/c19/moments/events {")
    transfer_auth = location_body("location = /_c19_asset_transfer_auth {")
    upload = location_body('location ~ "^/api/backend/c19-assets/u/[A-Za-z0-9_-]{43}$" {')
    download = location_body('location ~ "^/api/backend/c19-assets/d/[A-Za-z0-9_-]{43}$" {')

    assert "location = /_c19_asset_transfer_auth" in document
    assert "/api/app/c19/assets/transfers/authorize" in document
    assert "proxy_pass_request_body off;" in document
    assert "proxy_set_header Cookie $http_cookie;" in transfer_auth
    assert 'proxy_set_header Authorization "";' in transfer_auth
    assert 'proxy_set_header X-Session-Token "";' in transfer_auth
    assert "X-C19-Transfer-URI $c19_transfer_uri" in document
    assert "X-C19-Transfer-Method $c19_transfer_method" in document
    assert document.count("set $c19_transfer_uri $request_uri;") == 2
    assert document.count("set $c19_transfer_method $request_method;") == 2
    assert "^/api/backend/c19-assets/u/[A-Za-z0-9_-]{43}$" in document
    assert "^/api/backend/c19-assets/d/[A-Za-z0-9_-]{43}$" in document
    assert "location /api/backend/c19-assets/" in document
    assert "location ^~ /api/backend/c19-assets/" not in document
    assert "location = /api/backend/c19-assets" in document
    assert "location = /api/c19-assets" in document
    assert "location /api/c19-assets/" in document
    assert "client_max_body_size 64m;" in document
    assert "proxy_request_buffering off;" in document
    assert document.count("auth_request /_c19_asset_transfer_auth;") == 2
    assert document.count("access_log off;") >= 3
    for byte_location in (upload, download):
        assert "proxy_pass http://127.0.0.1:8092;" in byte_location
        assert "proxy_pass http://127.0.0.1:3000;" not in byte_location
        assert "proxy_pass http://127.0.0.1:8000;" not in byte_location
        assert 'proxy_set_header Cookie "";' in byte_location
        assert 'proxy_set_header Authorization "";' in byte_location
        assert 'proxy_set_header X-Session-Token "";' in byte_location
    for event_location in (sse, moment_sse):
        assert "proxy_buffering off;" in event_location
        assert "proxy_cache off;" in event_location
        assert 'proxy_set_header Cookie "";' not in event_location
        assert 'proxy_set_header Authorization "";' not in event_location
        assert 'proxy_set_header X-Session-Token "";' not in event_location
    assert "img-src 'self' data: blob:" in document
    assert "img-src 'self' data: blob: https:" in document


def test_deployment_cookie_path_covers_both_asset_byte_locators() -> None:
    ticket = "A" * 43
    locators = (
        f"/api/backend/c19-assets/u/{ticket}",
        f"/api/backend/c19-assets/d/{ticket}",
    )
    for relative_path in (
        ".env.example",
        ".env.staging.example",
        ".env.production.example",
    ):
        document = (ROOT / relative_path).read_text(encoding="utf-8")
        configured = re.search(
            r"(?m)^AUTH_SESSION_COOKIE_PATH=(?P<path>[^\s#]+)$",
            document,
        )
        assert configured is not None, relative_path
        cookie_path = configured.group("path").rstrip("/") or "/"
        assert cookie_path == "/api/backend", relative_path
        for locator in locators:
            assert locator.startswith(f"{cookie_path}/"), (relative_path, locator)


def test_record_backup_and_restore_gates_require_stage6_retention_schema() -> None:
    backup = (ROOT / "scripts/c19_record_backup.sh").read_text(
        encoding="utf-8"
    )
    restore = (ROOT / "scripts/c19_record_restore.sh").read_text(
        encoding="utf-8"
    )
    for table in (
        "moment_feed_sequence",
        "moments",
        "moment_audience_snapshots",
        "moment_asset_references",
        "moment_likes",
        "moment_comments",
        "moment_user_events",
        "record_asset_coordination",
        "record_asset_deletion_outbox",
        "record_retention_operations",
        "record_retention_batches",
    ):
        assert table in restore
    for safety_column in (
        "publish_intent_sha256",
        "delete_pending_at",
        "audience_org_ids",
        "event_sequence",
        "approved_maximum_records",
        "approved_maximum_asset_jobs",
        "cumulative_affected_count",
        "operation_complete",
        "retention_operation_id",
        "coordination_columns",
        "requested_by_user_id",
        "delete_before",
        "last_attempt_at",
        "authorized_at",
    ):
        assert safety_column in restore
    for required in (
        "c19_record_20260712_04",
        "record_asset_coordination",
        "record_asset_deletion_outbox",
        "record_retention_operations",
        "record_retention_batches",
    ):
        assert required in backup
    for schema_object in (
        "pk_record_asset_coordination",
        "pk_record_asset_deletion_outbox",
        "pk_record_retention_operations",
        "pk_record_retention_batches",
        "fk_record_asset_deletion_outbox_retention_operation_id__ecb1",
        "fk_record_retention_batches_operation_id_record_retenti_0030",
        "uq_record_asset_deletion_outbox_record_asset",
        "ck_record_asset_deletion_outbox_attempt_count_nonnegative",
        "ck_record_asset_deletion_outbox_state_supported",
        "ck_record_asset_deletion_outbox_outcome_supported",
        "ck_record_asset_deletion_outbox_lease_pair_consistent",
        "ck_record_asset_deletion_outbox_completion_consistent",
        "ck_record_asset_deletion_outbox_authorization_consistent",
        "ck_record_retention_operations_approved_maximum_supported",
        "ck_record_retention_operations_approved_asset_maximum_supported",
        "ck_record_retention_operations_asset_jobs_enqueued_with_3d91",
        "ck_record_retention_operations_asset_jobs_completed_wit_5f0c",
        "ck_record_retention_operations_affected_count_nonnegative",
        "ck_record_retention_operations_affected_within_approved_maximum",
        "ck_record_retention_operations_next_batch_ordinal_nonnegative",
        "ck_record_retention_batches_batch_ordinal_nonnegative",
        "ck_record_retention_batches_maximum_records_supported",
        "ck_record_retention_batches_affected_within_batch_maximum",
        "ck_record_retention_batches_cumulative_count_consistent",
        "ix_record_asset_deletion_outbox_state_created",
        "ix_record_asset_deletion_outbox_retention_operation",
        "ix_record_asset_deletion_outbox_asset_state",
        "ix_record_asset_deletion_outbox_lease_until",
        "ix_record_asset_deletion_outbox_authorized_at",
        "ix_record_retention_operations_completed_at",
    ):
        assert schema_object in restore
        assert schema_object in backup
    for strict_catalog_gate in (
        "constraint_record.convalidated",
        "constraint_record.contype",
        "constraint_record.confrelid",
        "constraint_record.conkey[1]",
        "constraint_record.confkey[1]",
        "constraint_record.confdeltype",
        "array_length(constraint_record.conkey, 1) = 1",
        "index_state.indisvalid",
        "index_state.indisready",
        "table_record.relname || ':'",
    ):
        assert strict_catalog_gate in restore
        assert strict_catalog_gate in backup
    assert "retention_operation_id:record_retention_operations:operation_id:r" in restore
    assert "operation_id:record_retention_operations:operation_id:r" in restore
    assert "retention_operation_id:record_retention_operations:operation_id:r" in backup
    assert "operation_id:record_retention_operations:operation_id:r" in backup
    assert '[[ "$revision" == "$required_revision" ]]' in backup
    assert '[[ "$expected_revision" == "$required_revision" ]]' in restore

    next_config = (ROOT / "frontend/next.config.ts").read_text(encoding="utf-8")
    assert "img-src 'self' data: blob:" in next_config
    assert "img-src 'self' data: blob: https:" in next_config


def test_asset_runtime_secrets_archives_and_backup_roles_are_isolated() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    example = (ROOT / ".env.c19-asset.production.example").read_text(
        encoding="utf-8"
    )
    backup = (ROOT / "scripts/c19_asset_backup.sh").read_text(encoding="utf-8")
    restore = (ROOT / "scripts/c19_asset_restore.sh").read_text(encoding="utf-8")
    operations = (ROOT / "docs/C19_ASSET_STORE_OPERATIONS.md").read_text(
        encoding="utf-8"
    )

    assert ".env.c19-asset.*" in gitignore
    assert "!.env.c19-asset.*.example" in gitignore
    assert "backups/c19-asset/" in gitignore
    assert "backups/c19-asset/" in dockerignore
    assert "C19_ASSET_SERVICE_TOKEN=CHANGE-ME-" in example
    assert "C19_ASSET_GATEWAY_TOKEN=CHANGE-ME-" in example

    assert "CONFIRM_C19_ASSET_BACKUP" in backup
    assert "pg_dump" in backup
    assert "objects.tar" in backup
    assert "manifest_sha256" in backup
    assert "incoming_and_quarantine_included: no" in backup
    assert "--leave-stopped" in backup
    assert "-m c19_asset_service.consistency" in backup
    assert "c19_asset_20260712_03" in backup
    for retention_schema_object in (
        "retention_operation_id",
        "retention_record_id",
        "retention_conversation_id",
        "retention_prepared_at",
        "ck_chat_assets_retention_preparation_consistent",
        "uq_chat_assets_retention_operation_id",
        "ix_chat_assets_retention_prepared_at",
    ):
        assert retention_schema_object in backup
        assert retention_schema_object in restore
    for exact_catalog_gate in (
        "constraint_record.convalidated",
        "constraint_record.contype",
        "index_state.indisvalid",
        "index_state.indisready",
        "chat_assets:ck_chat_assets_retention_preparation_consistent:c",
        "chat_assets:uq_chat_assets_retention_operation_id:u",
        "chat_assets:ix_chat_assets_retention_prepared_at",
    ):
        assert exact_catalog_gate in backup
        assert exact_catalog_gate in restore
    assert backup.index("stop -t 30 c19-asset-gateway c19-asset-api") < backup.index(
        "stop -t 180 c19-asset-worker"
    )
    assert "--drain-blocker-count" in backup
    assert backup.index("--drain-blocker-count") < backup.rindex(
        '"${compose[@]}" stop -t 180 c19-asset-worker'
    )
    for state in ("uploaded", "scanning", "delete_pending", "quarantined"):
        assert state in (ROOT / "c19_asset_service/consistency.py").read_text(
            encoding="utf-8"
        )
    assert "CONFIRM_C19_ASSET_RESTORE" in restore
    assert "Restore requires an isolated private network" in restore
    assert "Restore requires an isolated ClamAV update-egress network" in restore
    assert "Restore requires an isolated gateway loopback-ingress network" in restore
    assert "Restore must not join the production client network" in restore
    assert "Incoming, quarantine, and active target volumes must all be empty" in restore
    assert "Restore requires a fresh target PostgreSQL database" in restore
    assert "c19_asset_20260712_03" in restore
    assert "-m c19_asset_service.consistency --database-name" in restore
    assert restore.index("-m c19_asset_service.consistency --database-name") < restore.index(
        'ALTER DATABASE "$target_db" RENAME TO "$rollback_db"'
    )
    assert "Restored DB/object manifest does not match the accepted source set" in restore
    assert "Post-migration DB/object manifest no longer matches the source set" in restore
    assert "SET quarantine_object_key = NULL" in restore
    assert "UPDATE asset_transfer_tickets" in restore
    assert "SET revoked_at = CURRENT_TIMESTAMP" in restore
    assert "restore_exit_cleanup" in restore
    assert 'BEGIN;\nALTER DATABASE "$target_db" RENAME TO "$rollback_db";' in restore
    assert 'ALTER DATABASE "$rollback_db" RENAME TO "$target_db";' in restore
    assert "worker TTL deletes only `active + unbound`" in operations
    assert "all currently eligible" in operations
    assert "maximum_dispatch_jobs" in operations
    assert "explicit deletes" in operations
    assert "prepare or commit" in operations


def test_postgres_internal_char_catalog_values_are_cast_before_concatenation() -> None:
    scripts_with_constraint_types = (
        "scripts/c19_asset_backup.sh",
        "scripts/c19_asset_restore.sh",
        "scripts/c19_record_backup.sh",
        "scripts/c19_record_restore.sh",
        "scripts/c19_full_backup.sh",
    )
    for script_name in scripts_with_constraint_types:
        script = (ROOT / script_name).read_text(encoding="utf-8")
        assert "|| constraint_record.contype from" not in script
        if "|| constraint_record.contype" in script:
            assert "|| constraint_record.contype::text" in script
        assert "|| constraint_record.confdeltype from" not in script
        if "|| constraint_record.confdeltype" in script:
            assert "|| constraint_record.confdeltype::text" in script


def test_asset_operations_scripts_parse_and_help_without_runtime_secrets() -> None:
    for script_name in ("c19_asset_backup.sh", "c19_asset_restore.sh"):
        script = ROOT / "scripts" / script_name
        syntax = subprocess.run(
            ["bash", "-n", str(script)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert syntax.returncode == 0, syntax.stderr
        help_result = subprocess.run(
            [str(script), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert help_result.returncode == 0, help_result.stderr
        assert "Usage:" in help_result.stdout


def _write_restore_fixture(
    tmp_path: Path,
    *,
    unsafe_link: bool = False,
    revision: str = "c19_asset_20260712_03",
) -> Path:
    base = tmp_path / "c19_assets_20260711T000000Z"
    dump = base.with_suffix(".dump")
    objects = tmp_path / f"{base.name}.objects.tar"
    manifest = base.with_suffix(".manifest")
    metadata = base.with_suffix(".metadata")
    content = b"safe image bytes"
    dump.write_bytes(b"synthetic custom dump for dry-run validation")

    with tarfile.open(objects, mode="w") as archive:
        if unsafe_link:
            member = tarfile.TarInfo("objects/unsafe")
            member.type = tarfile.SYMTYPE
            member.linkname = "../../etc/passwd"
            archive.addfile(member)
        else:
            member = tarfile.TarInfo("aa/bb/" + "c" * 28)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))

    if unsafe_link:
        manifest.write_text("", encoding="utf-8")
        object_count = 0
        object_bytes = 0
    else:
        manifest.write_text(
            f"{hashlib.sha256(content).hexdigest()}\t{len(content)}\taa/bb/{'c' * 28}\n",
            encoding="utf-8",
        )
        object_count = 1
        object_bytes = len(content)

    metadata.write_text(
        "\n".join(
            (
                "created_at=20260711T000000Z",
                "source_dataset_id=barong-c19-assets-restore-test",
                f"alembic_revision={revision}",
                "blob_format_revision=1",
                "database_format=pg_dump_custom",
                "object_archive_format=posix_tar",
                f"object_count={object_count}",
                f"object_bytes={object_bytes}",
                f"database_sha256={hashlib.sha256(dump.read_bytes()).hexdigest()}",
                f"objects_sha256={hashlib.sha256(objects.read_bytes()).hexdigest()}",
                f"manifest_sha256={hashlib.sha256(manifest.read_bytes()).hexdigest()}",
                "",
            )
        ),
        encoding="utf-8",
    )
    return metadata


def _write_restore_env(tmp_path: Path) -> Path:
    env_file = tmp_path / "asset.env"
    password = "a" * 40
    env_file.write_text(
        "\n".join(
            (
                "C19_ASSET_DATASET_ID=barong-c19-assets-restore-test",
                "POSTGRES_DB=c19_chat_assets",
                "POSTGRES_USER=c19_asset_service",
                f"POSTGRES_PASSWORD={password}",
                f"C19_ASSET_DATABASE_URL=postgresql+psycopg://c19_asset_service:{password}@c19-asset-postgres:5432/c19_chat_assets",
                f"C19_ASSET_SERVICE_TOKEN={'b' * 40}",
                f"C19_ASSET_GATEWAY_TOKEN={'c' * 40}",
                "C19_ASSET_INCOMING_ROOT=/var/lib/c19-assets/incoming",
                "C19_ASSET_QUARANTINE_ROOT=/var/lib/c19-assets/quarantine",
                "C19_ASSET_ACTIVE_ROOT=/var/lib/c19-assets/active",
                "",
            )
        ),
        encoding="utf-8",
    )
    return env_file


def test_restore_dry_run_validates_complete_backup_without_docker_mutation(
    tmp_path: Path,
) -> None:
    metadata = _write_restore_fixture(tmp_path)
    env_file = _write_restore_env(tmp_path)
    environment = os.environ.copy()
    environment["C19_ASSET_ENV_FILE"] = str(env_file)

    result = subprocess.run(
        [
            str(ROOT / "scripts/c19_asset_restore.sh"),
            "--metadata",
            str(metadata),
            "--dry-run",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "C19 asset restore plan" in result.stdout
    assert "object_count: 1" in result.stdout
    assert "required_confirmation:" in result.stdout


def test_restore_dry_run_rejects_link_members_before_any_docker_mutation(
    tmp_path: Path,
) -> None:
    metadata = _write_restore_fixture(tmp_path, unsafe_link=True)
    env_file = _write_restore_env(tmp_path)
    environment = os.environ.copy()
    environment["C19_ASSET_ENV_FILE"] = str(env_file)

    result = subprocess.run(
        [
            str(ROOT / "scripts/c19_asset_restore.sh"),
            "--metadata",
            str(metadata),
            "--dry-run",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Object archive or manifest validation failed" in result.stderr


def test_asset_restore_rejects_pre_retention_revision_before_mutation(
    tmp_path: Path,
) -> None:
    metadata = _write_restore_fixture(
        tmp_path,
        revision="c19_asset_20260712_02",
    )
    env_file = _write_restore_env(tmp_path)
    environment = os.environ.copy()
    environment["C19_ASSET_ENV_FILE"] = str(env_file)

    result = subprocess.run(
        [
            str(ROOT / "scripts/c19_asset_restore.sh"),
            "--metadata",
            str(metadata),
            "--dry-run",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "requires Alembic revision c19_asset_20260712_03" in result.stderr
