from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _service_block(document: str, service_name: str) -> str:
    marker = f"  {service_name}:\n"
    start = document.index(marker) + len(marker)
    end = len(document)
    lines = document[start:].splitlines(keepends=True)
    offset = start
    for line in lines:
        if line.startswith("  ") and not line.startswith("    "):
            end = offset
            break
        offset += len(line)
    return document[start:end]


def test_record_stack_exposes_only_the_service_and_minimizes_container_secrets() -> None:
    document = (ROOT / "docker-compose.c19-record.yml").read_text(encoding="utf-8")
    database = _service_block(document, "c19-record-postgres")
    record_service = _service_block(document, "c19-record-service")

    assert "    ports:" not in database
    assert "    ports:" not in record_service
    assert '      - "8090"' in record_service
    assert "      - c19-record-private" in database
    assert "      - barong-ops-console-prod" not in database
    assert "      - c19-record-private" in record_service
    assert "      - barong-ops-console-prod" in record_service
    assert "    internal: true" in document
    assert "C19_RECORD_VOLUME_NAME:-c19_record_postgres_data" in document
    assert "com.barong.c19.dataset-id" in document
    assert "C19_RECORD_DATASET_ID:?C19_RECORD_DATASET_ID is required" in document
    assert "C19_RECORD_PRIVATE_NETWORK_NAME:-c19-record-private" in document
    assert "BARONG_SHARED_NETWORK_NAME:-barong-ops-console-prod" in document

    for key in (
        "C19_RECORD_DATABASE_URL",
        "C19_RECORD_SERVICE_TOKEN",
        "C19_RECORD_CURSOR_SIGNING_SECRET",
    ):
        assert f'      {key}: ""' in database

    for key in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        assert f'      {key}: ""' in record_service


def test_barong_record_token_is_effectively_available_only_to_backend() -> None:
    document = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
    backend = _service_block(document, "console_backend")
    assert "      - .env.production" in backend
    assert "C19_RECORD_STORE_TOKEN" not in backend

    for service_name in (
        "console_postgres",
        "r-w-worker",
        "r-a-worker",
        "k-worker",
        "key-health-worker",
        "console_frontend",
    ):
        service = _service_block(document, service_name)
        assert '      C19_RECORD_STORE_TOKEN: ""' in service
        assert '      C19_RECORD_STORE_URL: ""' in service


def test_runtime_record_env_and_archives_are_git_ignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert ".env.c19-record.*" in gitignore
    assert "!.env.c19-record.*.example" in gitignore
    assert "backups/c19-record/" in gitignore
    assert "*.dump" in gitignore
    assert "*.dump.metadata" in gitignore
    assert "backups/c19-record/" in dockerignore
    assert "*.dump" in dockerignore
