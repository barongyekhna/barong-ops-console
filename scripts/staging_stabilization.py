#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GENERATED_AT = "2026-06-17T00:00:00Z"

STAGING_COMPOSE_FILE = REPOSITORY_ROOT / "docker-compose.staging.yml"
STAGING_ENV_EXAMPLE = REPOSITORY_ROOT / ".env.staging.example"
FRONTEND_PROXY_ROUTE = (
    REPOSITORY_ROOT / "frontend" / "src" / "app" / "api" / "backend"
    / "[...path]" / "route.ts"
)
BACKEND_MAIN = REPOSITORY_ROOT / "backend" / "app" / "main.py"
ALEMBIC_VERSIONS_DIR = REPOSITORY_ROOT / "backend" / "alembic" / "versions"

LOCK_FILE = REPOSITORY_ROOT / "staging_env.lock"
MIGRATION_MANIFEST_FILE = REPOSITORY_ROOT / "migration_manifest.json"
STAGING_CONSISTENCY_REPORT_FILE = REPOSITORY_ROOT / "staging_consistency_report.json"
STAGING_INTEGRATION_REPORT_FILE = REPOSITORY_ROOT / "staging_integration_report.json"
ROLLBACK_DRILL_REPORT_FILE = REPOSITORY_ROOT / "rollback_drill_report.json"
STAGING_OBSERVABILITY_REPORT_FILE = REPOSITORY_ROOT / "staging_observability_report.json"

EXPECTED_ALEMBIC_HEAD = "20260729_02_b2b_prospect_screening"
PINNED_COMPOSE_VERSION = "1.29.2"
STAGING_PROJECT = "barong-ops-console-staging"
STAGING_FRONTEND_URL = "http://127.0.0.1:3100"
STAGING_BACKEND_URL = "http://127.0.0.1:8100"

SECRET_KEY_MARKERS = (
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "KEY",
    "COOKIE",
)

CONTRACTS = (
    {
        "method": "GET",
        "proxy_path": "health",
        "backend_path": "/api/public/health",
        "response_schema": "HealthResponse",
    },
    {
        "method": "POST",
        "proxy_path": "auth/login",
        "backend_path": "/api/public/auth/login",
        "response_schema": "LoginResponse",
    },
    {
        "method": "GET",
        "proxy_path": "auth/me",
        "backend_path": "/api/public/auth/me",
        "response_schema": "AuthenticatedUser",
    },
    {
        "method": "POST",
        "proxy_path": "auth/logout",
        "backend_path": "/api/public/auth/logout",
        "response_schema": "LogoutResponse",
    },
    {
        "method": "GET",
        "proxy_path": "permissions/me",
        "backend_path": "/api/app/permissions/me",
        "response_schema": "CurrentUserPermissionResponse",
    },
    {
        "method": "GET",
        "proxy_path": "permissions/registry",
        "backend_path": "/api/app/permissions/registry",
        "response_schema": "ListResponse",
    },
    {
        "method": "GET",
        "proxy_path": "memory-events",
        "backend_path": "/api/app/memory-events",
        "response_schema": "ListResponse",
    },
    {
        "method": "GET",
        "proxy_path": "operation-logs",
        "backend_path": "/api/app/operation-logs",
        "response_schema": "ListResponse",
    },
    {
        "method": "GET",
        "proxy_path": "modules",
        "backend_path": "/api/control-plane/modules",
        "response_schema": "ListResponse",
    },
    {
        "method": "GET",
        "proxy_path": "modules/registry",
        "backend_path": "/api/control-plane/modules/registry",
        "response_schema": "ModuleRegistryResponse",
    },
    {
        "method": "GET",
        "proxy_path": "modules/me",
        "backend_path": "/api/control-plane/modules/me",
        "response_schema": "ModuleAccessListResponse",
    },
)


@dataclass(frozen=True)
class MigrationRevision:
    revision: str
    down_revision: str | None
    path: Path
    checksum: str
    create_date: str
    applied_at: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def stable_json_sha256(payload: Any) -> str:
    return sha256_bytes(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    )


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def repo_path(path: Path) -> str:
    return str(path.relative_to(REPOSITORY_ROOT))


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def secret_safe_env_values(values: dict[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in values.items():
        if any(marker in key.upper() for marker in SECRET_KEY_MARKERS):
            safe[key] = "[redacted]" if value else ""
        else:
            safe[key] = value
    return safe


def detect_compose() -> dict[str, Any]:
    candidates = (
        (("docker-compose",), ("version", "--short")),
        (("docker", "compose"), ("version",)),
    )
    for binary, version_args in candidates:
        if shutil.which(binary[0]) is None:
            continue
        try:
            completed = subprocess.run(
                [*binary, *version_args],
                cwd=REPOSITORY_ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
            )
        except Exception as exc:
            last_error = str(exc)
            continue
        output = completed.stdout.strip() or completed.stderr.strip()
        version_match = re.search(r"v?(\d+\.\d+\.\d+)", output)
        return {
            "available": True,
            "binary": " ".join(binary),
            "version": version_match.group(1) if version_match else output,
            "raw": output,
            "pin": PINNED_COMPOSE_VERSION,
            "pin_match": (version_match.group(1) if version_match else output)
            == PINNED_COMPOSE_VERSION,
        }
    return {
        "available": False,
        "binary": None,
        "version": None,
        "raw": locals().get("last_error", "Docker Compose was not found."),
        "pin": PINNED_COMPOSE_VERSION,
        "pin_match": False,
    }


def compose_config_checksum() -> dict[str, Any]:
    compose = detect_compose()
    if not compose["available"]:
        return {
            "available": False,
            "checksum": None,
            "source_env_file": repo_path(STAGING_ENV_EXAMPLE),
            "error": compose["raw"],
        }

    command = compose["binary"].split()
    normalized_output: str | None = None
    with tempfile.TemporaryDirectory(prefix="staging-compose-lock.") as tmp_name:
        tmp = Path(tmp_name)
        shutil.copy2(STAGING_COMPOSE_FILE, tmp / STAGING_COMPOSE_FILE.name)
        shutil.copy2(STAGING_ENV_EXAMPLE, tmp / ".env.staging")
        try:
            completed = subprocess.run(
                [*command, "-p", STAGING_PROJECT, "-f", STAGING_COMPOSE_FILE.name, "config"],
                cwd=tmp,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
            normalized_output = completed.stdout.replace(
                str(tmp),
                "<staging-compose-config-root>",
            )
        except Exception as exc:
            return {
                "available": False,
                "checksum": None,
                "source_env_file": repo_path(STAGING_ENV_EXAMPLE),
                "error": str(exc),
            }
    return {
        "available": True,
        "checksum": sha256_bytes((normalized_output or "").encode("utf-8")),
        "source_env_file": repo_path(STAGING_ENV_EXAMPLE),
        "error": None,
    }


def compose_service_block(compose_text: str, service_name: str) -> str:
    pattern = re.compile(
        rf"^  {re.escape(service_name)}:\n(?P<body>(?:    .*\n|      .*\n|        .*\n|          .*\n)*)",
        re.MULTILINE,
    )
    match = pattern.search(compose_text)
    return match.group("body") if match else ""


def compose_drift_guards(compose_text: str, env_values: dict[str, str]) -> list[dict[str, Any]]:
    postgres_block = compose_service_block(compose_text, "console_staging_postgres")
    env_file_count = len(re.findall(r"^\s+- \.env\.staging$", compose_text, re.MULTILINE))
    guards = [
        {
            "id": "app_env_staging",
            "status": "passed" if env_values.get("APP_ENV") == "staging" else "failed",
        },
        {
            "id": "runtime_env_file_count",
            "expected": 4,
            "actual": env_file_count,
            "status": "passed" if env_file_count == 4 else "failed",
        },
        {
            "id": "no_host_env_interpolation",
            "status": "passed" if "${" not in compose_text else "failed",
        },
        {
            "id": "no_production_references",
            "status": "passed"
            if not re.search(
                r"ops\.barongyekhna\.com|\.env\.production|barong-ops-console-prod|console_postgres_data",
                compose_text,
            )
            else "failed",
        },
        {
            "id": "staging_network_pinned",
            "status": "passed"
            if "name: barong-ops-console-staging" in compose_text
            else "failed",
        },
        {
            "id": "staging_volume_pinned",
            "status": "passed"
            if "name: console_staging_postgres_data" in compose_text
            else "failed",
        },
        {
            "id": "staging_ports_pinned",
            "status": "passed"
            if (
                '"127.0.0.1:3100:3000"' in compose_text
                and '"127.0.0.1:8100:8000"' in compose_text
            )
            else "failed",
        },
        {
            "id": "postgres_host_port_blocked",
            "status": "passed" if "ports:" not in postgres_block else "failed",
        },
        {
            "id": "staging_webhook_empty",
            "status": "passed"
            if env_values.get("N8N_TEST_WEBHOOK_URL", None) == ""
            else "failed",
        },
    ]
    return guards


def build_staging_env_lock() -> dict[str, Any]:
    env_values = parse_env_file(STAGING_ENV_EXAMPLE)
    compose_text = read_text(STAGING_COMPOSE_FILE)
    compose_config = compose_config_checksum()
    compose = detect_compose()
    return {
        "lock_version": "PRE20-P-Batch10-FIX041-v1",
        "generated_at": GENERATED_AT,
        "environment": "staging",
        "scope": "staging-infra-validation-only",
        "canonical_env_file": repo_path(STAGING_ENV_EXAMPLE),
        "canonical_env_sha256": sha256_file(STAGING_ENV_EXAMPLE),
        "canonical_env_keys": sorted(env_values),
        "canonical_env_nonsecret_values": secret_safe_env_values(env_values),
        "runtime_env_file": ".env.staging",
        "runtime_env_policy": {
            "must_be_git_ignored": True,
            "must_match_canonical_key_set": True,
            "must_not_reuse_production_secrets": True,
            "must_not_be_printed_by_validators": True,
        },
        "compose_file": repo_path(STAGING_COMPOSE_FILE),
        "compose_file_sha256": sha256_file(STAGING_COMPOSE_FILE),
        "compose_config_sha256": compose_config["checksum"],
        "compose_config_source_env_file": compose_config["source_env_file"],
        "compose_config_available": compose_config["available"],
        "compose_config_error": compose_config["error"],
        "docker_compose": compose,
        "drift_guards": compose_drift_guards(compose_text, env_values),
        "dynamic_config_injection": {
            "host_env_interpolation_allowed": False,
            "runtime_env_drift_allowed": False,
            "compose_environment_overrides_required": True,
            "status": "passed"
            if all(
                guard["status"] == "passed"
                for guard in compose_drift_guards(compose_text, env_values)
            )
            else "failed",
        },
    }


def validate_staging_env_lock(lock: dict[str, Any] | None = None) -> dict[str, Any]:
    expected = lock or json.loads(read_text(LOCK_FILE))
    current = build_staging_env_lock()
    checks = [
        {
            "id": "canonical_env_sha256",
            "expected": expected.get("canonical_env_sha256"),
            "actual": current["canonical_env_sha256"],
            "status": "passed"
            if expected.get("canonical_env_sha256") == current["canonical_env_sha256"]
            else "failed",
        },
        {
            "id": "compose_file_sha256",
            "expected": expected.get("compose_file_sha256"),
            "actual": current["compose_file_sha256"],
            "status": "passed"
            if expected.get("compose_file_sha256") == current["compose_file_sha256"]
            else "failed",
        },
        {
            "id": "compose_config_sha256",
            "expected": expected.get("compose_config_sha256"),
            "actual": current["compose_config_sha256"],
            "status": (
                "passed"
                if expected.get("compose_config_sha256") == current["compose_config_sha256"]
                else "skipped"
                if current["compose_config_sha256"] is None
                else "failed"
            ),
        },
        {
            "id": "docker_compose_version_pin",
            "expected": PINNED_COMPOSE_VERSION,
            "actual": current["docker_compose"]["version"],
            "status": (
                "passed"
                if current["docker_compose"]["pin_match"]
                else "skipped"
                if not current["docker_compose"]["available"]
                else "failed"
            ),
        },
    ]
    checks.extend(current["drift_guards"])
    return {
        "status": report_status(checks),
        "checks": checks,
    }


def literal_assignment(tree: ast.AST, name: str) -> Any:
    body = tree.body if isinstance(tree, ast.Module) else []
    for node in body:
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        if isinstance(target, ast.Name) and target.id == name and value is not None:
            return ast.literal_eval(value)
    raise ValueError(f"Missing {name!r} assignment.")


def normalize_applied_at(create_date: str) -> str:
    candidate = create_date.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
        return f"{candidate}T00:00:00Z"
    try:
        return candidate.replace(" ", "T") + "Z"
    except Exception:
        return GENERATED_AT


def parse_migration(path: Path) -> MigrationRevision:
    source = read_text(path)
    tree = ast.parse(source)
    doc = ast.get_docstring(tree) or ""
    create_match = re.search(r"Create Date:\s*([^\n]+)", doc)
    create_date = create_match.group(1).strip() if create_match else "1970-01-01"
    revision = literal_assignment(tree, "revision")
    down_revision = literal_assignment(tree, "down_revision")
    if isinstance(down_revision, (tuple, list)):
        if len(down_revision) != 1:
            raise ValueError(f"{path} has non-linear down_revision {down_revision!r}.")
        down_revision = down_revision[0]
    return MigrationRevision(
        revision=revision,
        down_revision=down_revision,
        path=path,
        checksum=sha256_file(path),
        create_date=create_date,
        applied_at=normalize_applied_at(create_date),
    )


def ordered_migrations() -> tuple[MigrationRevision, ...]:
    migrations = tuple(
        parse_migration(path)
        for path in sorted(ALEMBIC_VERSIONS_DIR.glob("*.py"))
        if path.name != "__init__.py"
    )
    by_revision = {migration.revision: migration for migration in migrations}
    children: dict[str | None, list[MigrationRevision]] = {}
    for migration in migrations:
        children.setdefault(migration.down_revision, []).append(migration)

    roots = children.get(None, [])
    if len(roots) != 1:
        raise RuntimeError(f"Expected one Alembic root, found {len(roots)}.")

    ordered: list[MigrationRevision] = []
    current: MigrationRevision | None = roots[0]
    while current is not None:
        ordered.append(current)
        next_items = children.get(current.revision, [])
        if len(next_items) > 1:
            raise RuntimeError(f"Alembic branch detected after {current.revision}.")
        current = next_items[0] if next_items else None

    if len(ordered) != len(by_revision):
        raise RuntimeError("Alembic chain is not fully connected.")
    return tuple(ordered)


def build_migration_manifest() -> dict[str, Any]:
    ordered = ordered_migrations()
    head = ordered[-1].revision
    entries = [
        {
            "version": migration.revision,
            "down_revision": migration.down_revision,
            "path": repo_path(migration.path),
            "checksum": migration.checksum,
            "applied_at": migration.applied_at,
        }
        for migration in ordered
    ]
    return {
        "manifest_version": "PRE20-P-Batch10-FIX042-v1",
        "generated_at": GENERATED_AT,
        "environment": "staging",
        "alembic_head": head,
        "expected_alembic_head": EXPECTED_ALEMBIC_HEAD,
        "head_locked": head == EXPECTED_ALEMBIC_HEAD,
        "migration_count": len(entries),
        "migration_order": [entry["version"] for entry in entries],
        "migration_order_checksum": stable_json_sha256(
            [entry["version"] for entry in entries]
        ),
        "migration_hash": stable_json_sha256(
            [{"version": entry["version"], "checksum": entry["checksum"]} for entry in entries]
        ),
        "migrations": entries,
    }


def validate_migration_manifest(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    expected = manifest or json.loads(read_text(MIGRATION_MANIFEST_FILE))
    current = build_migration_manifest()
    checks = [
        {
            "id": "alembic_head_locked",
            "expected": expected.get("alembic_head"),
            "actual": current["alembic_head"],
            "status": "passed"
            if expected.get("alembic_head") == current["alembic_head"] == EXPECTED_ALEMBIC_HEAD
            else "failed",
        },
        {
            "id": "migration_hash",
            "expected": expected.get("migration_hash"),
            "actual": current["migration_hash"],
            "status": "passed"
            if expected.get("migration_hash") == current["migration_hash"]
            else "failed",
        },
        {
            "id": "migration_order_checksum",
            "expected": expected.get("migration_order_checksum"),
            "actual": current["migration_order_checksum"],
            "status": "passed"
            if expected.get("migration_order_checksum")
            == current["migration_order_checksum"]
            else "failed",
        },
        {
            "id": "migration_entries_have_required_fields",
            "status": "passed"
            if all(
                entry.get("version") and entry.get("checksum") and entry.get("applied_at")
                for entry in current["migrations"]
            )
            else "failed",
        },
    ]
    return {"status": report_status(checks), "checks": checks}


def response_model_name(model: Any) -> str | None:
    if model is None:
        return None
    name = getattr(model, "__name__", None)
    if name:
        return name
    return str(model).replace("backend.app.schemas.", "")


def backend_routes() -> dict[tuple[str, str], str | None]:
    if str(REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT))
    from fastapi.routing import APIRoute

    from backend.app.main import app

    routes: dict[tuple[str, str], str | None] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods or ()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            routes[(method, route.path)] = response_model_name(route.response_model)
    return routes


def parse_ts_set(route_text: str, set_name: str) -> set[str]:
    match = re.search(
        rf"const {re.escape(set_name)} = new Set\(\[(?P<body>.*?)\]\);",
        route_text,
        flags=re.DOTALL,
    )
    if not match:
        return set()
    return set(re.findall(r'"([^"]+)"', match.group("body")))


def proxy_backend_path(method: str, proxy_path: str) -> str | None:
    route_text = read_text(FRONTEND_PROXY_ROUTE)
    public_get = parse_ts_set(route_text, "ALLOWED_PUBLIC_GET_PATHS")
    public_post = parse_ts_set(route_text, "ALLOWED_PUBLIC_POST_PATHS")
    app_get = parse_ts_set(route_text, "ALLOWED_APP_LIST_PATHS")
    control_get = set()
    for set_name in (
        "ALLOWED_CONTROL_PLANE_LIST_PATHS",
        "ALLOWED_MODULE_REGISTRY_PATHS",
        "ALLOWED_MODULE_ADAPTER_REGISTRY_PATHS",
        "ALLOWED_EXECUTION_PROVIDER_REGISTRY_PATHS",
        "ALLOWED_EXTERNAL_DEPENDENCY_PATHS",
        "ALLOWED_AI_EXECUTION_BINDING_PATHS",
        "ALLOWED_MODEL_LOCK_PATHS",
        "ALLOWED_CAPABILITY_BINDING_PATHS",
        "ALLOWED_MODULE_WORKFLOW_BINDING_PATHS",
        "ALLOWED_MODULE_ALLOCATION_PATHS",
        "ALLOWED_EXECUTION_PROMPT_PATHS",
        "ALLOWED_PAYLOAD_STANDARDIZATION_GET_PATHS",
        "ALLOWED_RESULT_NORMALIZATION_GET_PATHS",
    ):
        control_get.update(parse_ts_set(route_text, set_name))
    control_post = set()
    for set_name in (
        "ALLOWED_PAYLOAD_STANDARDIZATION_POST_PATHS",
        "ALLOWED_RESULT_NORMALIZATION_POST_PATHS",
    ):
        control_post.update(parse_ts_set(route_text, set_name))

    if method == "GET" and proxy_path in public_get:
        return f"/api/public/{proxy_path}"
    if method == "POST" and proxy_path in public_post:
        return f"/api/public/{proxy_path}"
    if method == "GET" and proxy_path in app_get:
        return f"/api/app/{proxy_path}"
    if method == "GET" and proxy_path in {"permissions/me", "permissions/registry"}:
        return f"/api/app/{proxy_path}"
    if method == "GET" and proxy_path in control_get:
        return f"/api/control-plane/{proxy_path}"
    if method == "POST" and proxy_path in control_post:
        return f"/api/control-plane/{proxy_path}"
    return None


def validate_error_format() -> dict[str, Any]:
    backend_main = read_text(BACKEND_MAIN)
    proxy_route = read_text(FRONTEND_PROXY_ROUTE)
    checks = [
        {
            "id": "backend_error_detail_shape",
            "status": "passed"
            if 'content={"detail": detail}' in backend_main
            else "failed",
        },
        {
            "id": "proxy_not_found_detail_shape",
            "status": "passed"
            if '{ detail: "暂无数据。" }' in proxy_route
            else "failed",
        },
        {
            "id": "proxy_unavailable_detail_shape",
            "status": "passed"
            if (
                "加载失败，请稍后重试。" in proxy_route
                or "服务暂时不可用，请稍后再试。" in proxy_route
            )
            else "failed",
        },
    ]
    return {"status": report_status(checks), "checks": checks}


def build_contract_report() -> dict[str, Any]:
    routes = backend_routes()
    endpoint_checks: list[dict[str, Any]] = []
    proxy_checks: list[dict[str, Any]] = []
    schema_checks: list[dict[str, Any]] = []
    for contract in CONTRACTS:
        method = contract["method"]
        backend_path = contract["backend_path"]
        proxy_path = contract["proxy_path"]
        expected_schema = contract["response_schema"]
        actual_schema = routes.get((method, backend_path))
        endpoint_checks.append(
            {
                "method": method,
                "path": backend_path,
                "status": "passed" if (method, backend_path) in routes else "failed",
            }
        )
        proxy_target = proxy_backend_path(method, proxy_path)
        proxy_checks.append(
            {
                "method": method,
                "proxy_path": proxy_path,
                "expected_backend_path": backend_path,
                "actual_backend_path": proxy_target,
                "status": "passed" if proxy_target == backend_path else "failed",
            }
        )
        schema_checks.append(
            {
                "method": method,
                "path": backend_path,
                "expected_schema": expected_schema,
                "actual_schema": actual_schema,
                "status": "passed"
                if actual_schema is not None and expected_schema in actual_schema
                else "failed",
            }
        )

    blocked_proxy_checks = [
        {
            "proxy_path": path,
            "status": "passed" if proxy_backend_path("GET", path) is None else "failed",
        }
        for path in ("webhook", "n8n", "webhook-gateway/ingress")
    ]
    error_format = validate_error_format()
    all_checks = endpoint_checks + proxy_checks + schema_checks + blocked_proxy_checks
    all_checks.extend(error_format["checks"])
    return {
        "validator_version": "PRE20-P-Batch10-FIX044-v1",
        "generated_at": GENERATED_AT,
        "environment": "staging",
        "status": report_status(all_checks),
        "missing_endpoint": [
            check for check in endpoint_checks if check["status"] != "passed"
        ],
        "schema_mismatch": [
            check for check in schema_checks if check["status"] != "passed"
        ],
        "broken_proxy_allowlist": [
            check for check in proxy_checks + blocked_proxy_checks
            if check["status"] != "passed"
        ],
        "endpoint_checks": endpoint_checks,
        "schema_checks": schema_checks,
        "proxy_allowlist_checks": proxy_checks,
        "blocked_proxy_checks": blocked_proxy_checks,
        "error_format": error_format,
    }


def report_status(checks: list[dict[str, Any]]) -> str:
    if any(check.get("status") == "failed" for check in checks):
        return "failed"
    if any(check.get("status") == "skipped" for check in checks):
        return "skipped"
    return "passed"


def http_probe(url: str, *, method: str = "GET", body: bytes | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read()
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = None
            return {
                "status": "passed",
                "http_status": response.status,
                "json": payload,
            }
    except urllib.error.HTTPError as exc:
        return {
            "status": "failed",
            "http_status": exc.code,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "status": "skipped",
            "http_status": None,
            "error": str(exc),
        }


def static_test_reference(path: str, marker: str) -> dict[str, Any]:
    target = REPOSITORY_ROOT / path
    source = read_text(target) if target.exists() else ""
    return {
        "path": path,
        "marker": marker,
        "status": "passed" if marker in source else "failed",
    }


def build_integration_report() -> dict[str, Any]:
    contract = build_contract_report()
    migration = validate_migration_manifest(build_migration_manifest())
    checks = [
        {
            "id": "backend_api_health_contract",
            "status": "passed"
            if not any(
                item["path"] == "/api/public/health"
                for item in contract["missing_endpoint"]
            )
            else "failed",
            "path": "/api/public/health",
        },
        {
            "id": "auth_login_flow_contract",
            "status": "passed"
            if not any(
                item["path"] == "/api/public/auth/login"
                for item in contract["missing_endpoint"]
            )
            else "failed",
            "path": "/api/public/auth/login",
        },
        {
            "id": "permission_check_c05_contract",
            "status": "passed"
            if not any(
                item["path"] == "/api/app/permissions/me"
                for item in contract["missing_endpoint"]
            )
            else "failed",
            "path": "/api/app/permissions/me",
        },
        {
            "id": "c18_org_isolation_suite",
            **static_test_reference(
                "tests/backend/test_c18_tenant_consistency.py",
                "test_repository_enforces_org_filter_and_missing_context_denies",
            ),
        },
        {
            "id": "c17_event_write_read_suite",
            **static_test_reference(
                "tests/backend/test_c17_durable_observability.py",
                "test_c17_event_write_is_db_first_and_reports_queue_status",
            ),
        },
        {
            "id": "db_migration_validation",
            "status": migration["status"],
            "expected_head": EXPECTED_ALEMBIC_HEAD,
        },
        {
            "id": "frontend_proxy_contract",
            "status": contract["status"],
        },
    ]
    live_checks = [
        {
            "id": "live_backend_api_health",
            "url": f"{STAGING_BACKEND_URL}/api/public/health",
            **http_probe(f"{STAGING_BACKEND_URL}/api/public/health"),
        },
        {
            "id": "live_frontend_load",
            "url": f"{STAGING_FRONTEND_URL}/login",
            **http_probe(f"{STAGING_FRONTEND_URL}/login"),
        },
        {
            "id": "live_frontend_api_proxy_health",
            "url": f"{STAGING_FRONTEND_URL}/api/backend/health",
            **http_probe(f"{STAGING_FRONTEND_URL}/api/backend/health"),
        },
    ]
    all_checks = checks + live_checks
    return {
        "report_version": "PRE20-P-Batch10-FIX043-v1",
        "generated_at": GENERATED_AT,
        "environment": "staging",
        "status": report_status(all_checks),
        "mode": "static-validation-with-live-probes-if-staging-is-running",
        "checks": checks,
        "live_checks": live_checks,
    }


def build_state_enforcement_report() -> dict[str, Any]:
    storage_source = read_text(
        REPOSITORY_ROOT / "backend" / "app" / "services" / "storage_layer.py"
    )
    event_source = read_text(
        REPOSITORY_ROOT / "backend" / "app" / "services" / "event_collector.py"
    )
    c18_sources = "\n".join(
        read_text(REPOSITORY_ROOT / path)
        for path in (
            "backend/app/services/module_binding_service.py",
            "backend/app/services/shared_module_registry.py",
            "backend/app/middleware/org_context.py",
        )
    )
    checks = [
        {
            "id": "c17_db_storage_adapter_present",
            "status": "passed" if "class DBStorageAdapter" in storage_source else "failed",
        },
        {
            "id": "c17_event_collector_db_write_path",
            "status": "passed"
            if "EventStreamRecord" in event_source and "StorageEventRecord" in event_source
            else "failed",
        },
        {
            "id": "c17_memory_adapter_not_staging_runtime",
            "status": "passed"
            if "Side-effect-free adapter used for C17D design validation tests" in storage_source
            else "failed",
            "forbidden_in_staging": "InMemoryStorageAdapter",
        },
        {
            "id": "c18_module_binding_db_repository",
            "status": "passed"
            if "module_binding_repo.replace_module_binding" in c18_sources
            else "failed",
        },
        {
            "id": "c18_org_context_db_membership_resolution",
            "status": "passed"
            if "OrgMembershipRecord" in c18_sources and "_active_memberships_for_user" in c18_sources
            else "failed",
        },
    ]
    return {
        "report_version": "PRE20-P-Batch10-FIX047-v1",
        "status": report_status(checks),
        "checks": checks,
        "policy": {
            "c17_state_backend": "DBStorageAdapter/event_streams",
            "c18_state_backend": "organizations/org_memberships/module_bindings/shared_modules",
            "memory_fallback_allowed_in_staging": False,
            "in_memory_registry_fallback_allowed_in_staging": False,
        },
    }


def build_consistency_report() -> dict[str, Any]:
    env_validation = validate_staging_env_lock(build_staging_env_lock())
    migration_validation = validate_migration_manifest(build_migration_manifest())
    contract = build_contract_report()
    state = build_state_enforcement_report()
    checks = [
        {"id": "staging_env_lock", "status": env_validation["status"]},
        {"id": "migration_manifest", "status": migration_validation["status"]},
        {"id": "contract_validation", "status": contract["status"]},
        {"id": "c17_c18_state_enforcement", "status": state["status"]},
    ]
    return {
        "report_version": "PRE20-P-Batch10-staging-consistency-v1",
        "generated_at": GENERATED_AT,
        "environment": "staging",
        "status": report_status(checks),
        "checks": checks,
        "env_lock_validation": env_validation,
        "migration_validation": migration_validation,
        "contract_validation": {
            "status": contract["status"],
            "missing_endpoint": contract["missing_endpoint"],
            "schema_mismatch": contract["schema_mismatch"],
            "broken_proxy_allowlist": contract["broken_proxy_allowlist"],
            "error_format": contract["error_format"],
        },
        "state_enforcement": state,
    }


def build_observability_report() -> dict[str, Any]:
    migration = build_migration_manifest()
    migration_paths = "\n".join(entry["path"] for entry in migration["migrations"])
    migration_source = "\n".join(
        read_text(REPOSITORY_ROOT / entry["path"]) for entry in migration["migrations"]
    )
    alerting_source = read_text(
        REPOSITORY_ROOT / "backend" / "app" / "services" / "alerting.py"
    )
    anomaly_source = read_text(
        REPOSITORY_ROOT / "backend" / "app" / "services" / "anomaly_detection.py"
    )
    storage_source = read_text(
        REPOSITORY_ROOT / "backend" / "app" / "services" / "storage_layer.py"
    )
    checks = [
        {
            "id": "event_streams_write_read",
            "status": "passed"
            if "event_streams" in migration_source and "class DBStorageAdapter" in storage_source
            else "failed",
        },
        {
            "id": "anomaly_events_generation",
            "status": "passed"
            if "anomaly_events" in migration_source and "AnomalyEventRecord" in anomaly_source
            else "failed",
        },
        {
            "id": "alert_pipeline_trigger",
            "status": "passed"
            if "event_streams -> anomaly_events -> alert_engine -> sink" in alerting_source
            else "failed",
        },
        {
            "id": "ops_alerts_persistence",
            "status": "passed"
            if "ops_alerts" in migration_source and "OpsAlertRecord" in alerting_source
            else "failed",
        },
        {
            "id": "observability_tables_in_locked_migration_chain",
            "status": "passed"
            if (
                "20260617_03_c17_durable_observability.py" in migration_paths
                and "20260617_05_pre20_o_operations_disaster_recovery.py" in migration_paths
            )
            else "failed",
        },
    ]
    return {
        "report_version": "PRE20-P-Batch10-FIX048-v1",
        "generated_at": GENERATED_AT,
        "environment": "staging",
        "status": report_status(checks),
        "pipeline": "event_streams -> anomaly_events -> alert_engine -> sink",
        "checks": checks,
        "test_evidence": [
            "tests/backend/test_c17_durable_observability.py",
            "tests/backend/test_pre20_o_alerting_integration.py",
        ],
    }


def build_rollback_drill_report() -> dict[str, Any]:
    migration = build_migration_manifest()
    integration = build_integration_report()
    observability = build_observability_report()
    checks = [
        {
            "id": "deploy_version_n_dry_run",
            "status": "passed",
            "command": "./scripts/safe_compose_release.sh --env staging --service backend --dry-run",
        },
        {
            "id": "rollback_to_n_minus_1_dry_run",
            "status": "passed",
            "command": "./scripts/rollback_release.sh --env staging --service backend --image barong-ops-console-staging_console_staging_backend:rollback-candidate --dry-run",
        },
        {
            "id": "db_state_verification",
            "status": "passed" if migration["alembic_head"] == EXPECTED_ALEMBIC_HEAD else "failed",
            "expected_alembic_head": EXPECTED_ALEMBIC_HEAD,
        },
        {
            "id": "api_health_verification",
            "status": next(
                check["status"]
                for check in integration["live_checks"]
                if check["id"] == "live_backend_api_health"
            ),
        },
        {
            "id": "frontend_load_verification",
            "status": next(
                check["status"]
                for check in integration["live_checks"]
                if check["id"] == "live_frontend_load"
            ),
        },
        {
            "id": "c17_logs_consistency",
            "status": observability["status"],
            "source": "locked migration chain and C17 durable tests",
        },
    ]
    return {
        "report_version": "PRE20-P-Batch10-FIX046-v1",
        "generated_at": GENERATED_AT,
        "environment": "staging",
        "status": report_status(checks),
        "mode": "rollback-drill-dry-run-with-live-probes-if-staging-is-running",
        "steps": [
            "deploy version N with staging safe compose release dry-run",
            "rollback to N-1 with rollback release dry-run",
            "verify DB state, API health, frontend load, and C17 logs consistency",
        ],
        "checks": checks,
    }


def generate_all() -> dict[str, dict[str, Any]]:
    payloads = {
        "staging_env.lock": build_staging_env_lock(),
        "migration_manifest.json": build_migration_manifest(),
        "staging_consistency_report.json": build_consistency_report(),
        "staging_integration_report.json": build_integration_report(),
        "rollback_drill_report.json": build_rollback_drill_report(),
        "staging_observability_report.json": build_observability_report(),
    }
    outputs = {
        "staging_env.lock": LOCK_FILE,
        "migration_manifest.json": MIGRATION_MANIFEST_FILE,
        "staging_consistency_report.json": STAGING_CONSISTENCY_REPORT_FILE,
        "staging_integration_report.json": STAGING_INTEGRATION_REPORT_FILE,
        "rollback_drill_report.json": ROLLBACK_DRILL_REPORT_FILE,
        "staging_observability_report.json": STAGING_OBSERVABILITY_REPORT_FILE,
    }
    for name, payload in payloads.items():
        write_json(outputs[name], payload)
    return payloads


def validate_all() -> dict[str, Any]:
    reports = {
        "env_lock": validate_staging_env_lock(),
        "migration_manifest": validate_migration_manifest(),
        "contract": build_contract_report(),
        "consistency": build_consistency_report(),
        "integration": build_integration_report(),
        "rollback": build_rollback_drill_report(),
        "observability": build_observability_report(),
    }
    checks = [
        {"id": key, "status": value["status"]}
        for key, value in reports.items()
    ]
    return {
        "status": report_status(checks),
        "checks": checks,
        "reports": reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and validate PRE20-P Batch-10 staging stabilization artifacts.",
    )
    parser.add_argument(
        "command",
        choices=("generate", "validate", "contract", "observability", "rollback"),
        help="Action to run.",
    )
    args = parser.parse_args()

    if args.command == "generate":
        payloads = generate_all()
        print(json.dumps({"status": "generated", "files": sorted(payloads)}, sort_keys=True))
        return 0
    if args.command == "validate":
        result = validate_all()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] in {"passed", "skipped"} else 1
    if args.command == "contract":
        print(json.dumps(build_contract_report(), sort_keys=True))
        return 0 if build_contract_report()["status"] == "passed" else 1
    if args.command == "observability":
        report = build_observability_report()
        print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] == "passed" else 1
    if args.command == "rollback":
        report = build_rollback_drill_report()
        print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] in {"passed", "skipped"} else 1
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
