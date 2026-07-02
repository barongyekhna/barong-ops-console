"""Production persistence validation for R System v2."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPOSE_FILE = REPO_ROOT / "docker-compose.production.yml"
DEFAULT_RW_SCHEMA_SQL = REPO_ROOT / "r_system_v2" / "db" / "schema_rw.sql"
DEFAULT_POSTGRES_SERVICE = "console_postgres"
DEFAULT_BACKEND_SERVICE = "console_backend"
DEFAULT_POSTGRES_VOLUME = "console_postgres_data"
REQUIRED_PRODUCTS_RW_COLUMNS = frozenset(
    {
        "asin",
        "marketplace",
        "source_query",
        "title",
        "brand",
        "category",
        "category_id",
        "category_path",
        "price",
        "bsr",
        "reviews",
        "seller_count",
        "landed_cost",
        "est_net_margin",
        "brand_share",
        "price_trend",
        "rating",
        "skill_score",
        "state",
        "features",
        "created_at",
        "updated_at",
    }
)


@dataclass(frozen=True)
class ValidationStep:
    status: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersistenceValidationReport:
    generated_at: str
    connection_mode: str
    schema: ValidationStep
    write_read_cycle: ValidationStep
    backend_restart: ValidationStep
    read_after_restart: ValidationStep
    docker_volume: ValidationStep
    cleanup: ValidationStep
    persistence_verified: bool
    db_volume_stable: bool
    restart_safe_confirmed: bool
    no_in_memory_state: bool

    @property
    def deployment_allowed(self) -> bool:
        return all(
            [
                self.persistence_verified,
                self.db_volume_stable,
                self.restart_safe_confirmed,
                self.no_in_memory_state,
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema"] = self.schema.to_dict()
        payload["write_read_cycle"] = self.write_read_cycle.to_dict()
        payload["backend_restart"] = self.backend_restart.to_dict()
        payload["read_after_restart"] = self.read_after_restart.to_dict()
        payload["docker_volume"] = self.docker_volume.to_dict()
        payload["cleanup"] = self.cleanup.to_dict()
        payload["deployment_allowed"] = self.deployment_allowed
        return payload


class PersistenceValidationError(RuntimeError):
    pass


class PersistenceValidator:
    """Validate R-W persistence against a real PostgreSQL production database."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        compose_file: Path = DEFAULT_COMPOSE_FILE,
        postgres_service: str = DEFAULT_POSTGRES_SERVICE,
        backend_service: str = DEFAULT_BACKEND_SERVICE,
        postgres_volume: str = DEFAULT_POSTGRES_VOLUME,
        use_docker_psql: bool = False,
        apply_schema: bool = False,
        schema_sql_path: Path = DEFAULT_RW_SCHEMA_SQL,
    ) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL", "")
        self.compose_file = compose_file
        self.postgres_service = postgres_service
        self.backend_service = backend_service
        self.postgres_volume = postgres_volume
        self.use_docker_psql = use_docker_psql or not self.database_url
        self.apply_schema = apply_schema
        self.schema_sql_path = schema_sql_path
        self.asin = f"RWPERSIST{datetime.now(UTC).strftime('%H%M%S')}"[:10]

    def validate(self, *, restart_backend: bool = False) -> PersistenceValidationReport:
        schema = self.verify_schema()
        write_read = self.verify_write_read_cycle() if schema.status == "PASS" else _skipped("schema failed")
        backend_restart = (
            self.restart_backend_container()
            if write_read.status == "PASS" and restart_backend
            else _failed("backend restart was not executed")
        )
        read_after_restart = (
            self.verify_read_after_restart()
            if backend_restart.status == "PASS"
            else _failed("read-after-restart blocked because backend restart failed or was skipped")
        )
        docker_volume = self.verify_docker_volume()
        cleanup = self.cleanup_probe_row() if write_read.status == "PASS" else _skipped("nothing inserted")
        persistence_verified = write_read.status == "PASS" and read_after_restart.status == "PASS"
        db_volume_stable = docker_volume.status == "PASS"
        restart_safe_confirmed = backend_restart.status == "PASS" and read_after_restart.status == "PASS"
        no_in_memory_state = self.connection_mode != "memory" and schema.status == "PASS"
        return PersistenceValidationReport(
            generated_at=datetime.now(UTC).isoformat(),
            connection_mode=self.connection_mode,
            schema=schema,
            write_read_cycle=write_read,
            backend_restart=backend_restart,
            read_after_restart=read_after_restart,
            docker_volume=docker_volume,
            cleanup=cleanup,
            persistence_verified=persistence_verified,
            db_volume_stable=db_volume_stable,
            restart_safe_confirmed=restart_safe_confirmed,
            no_in_memory_state=no_in_memory_state,
        )

    @property
    def connection_mode(self) -> str:
        if self.use_docker_psql:
            return "docker_psql"
        if self.database_url.startswith("postgresql"):
            return "postgresql_url"
        if self.database_url.startswith("sqlite") or self.database_url == "":
            return "memory"
        return "unsupported"

    def verify_schema(self) -> ValidationStep:
        if self.connection_mode == "memory":
            return _failed("DATABASE_URL missing and docker psql mode disabled or unavailable")
        if self.connection_mode == "unsupported":
            return _failed("DATABASE_URL is not PostgreSQL")
        try:
            columns = set(self._column_names("products_rw"))
        except Exception as exc:
            return _failed(f"schema query failed: {exc}")
        missing = sorted(REQUIRED_PRODUCTS_RW_COLUMNS - columns)
        if missing and self.apply_schema:
            applied = self.apply_rw_schema()
            if applied.status != "PASS":
                return applied
            columns = set(self._column_names("products_rw"))
            missing = sorted(REQUIRED_PRODUCTS_RW_COLUMNS - columns)
        if missing:
            return _failed("products_rw schema missing required columns", {"missing": missing})
        return _passed("products_rw PostgreSQL schema verified", {"required_columns": sorted(REQUIRED_PRODUCTS_RW_COLUMNS)})

    def apply_rw_schema(self) -> ValidationStep:
        if not self.schema_sql_path.exists():
            return _failed("R-W schema SQL file missing", {"path": str(self.schema_sql_path)})
        try:
            self._execute_sql(self.schema_sql_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return _failed(f"R-W schema initialization failed: {exc}")
        return _passed("R-W schema initialized from schema_rw.sql", {"path": str(self.schema_sql_path)})

    def verify_write_read_cycle(self) -> ValidationStep:
        features = json.dumps(
            {
                "audit": "rw_persistence_gate",
                "created_at": datetime.now(UTC).isoformat(),
            },
            sort_keys=True,
        )
        sql = f"""
        INSERT INTO products_rw (
            asin, marketplace, source_query, title, brand, category, category_id,
            category_path, price, bsr, reviews, seller_count, landed_cost,
            est_net_margin, brand_share, price_trend, rating, skill_score,
            state, features
        )
        VALUES (
            '{self.asin}', 'US', 'rw persistence validation',
            'R-W Persistence Validation Product', 'BarongAudit',
            'Home & Kitchen', 'home-draft-proofing',
            'home-draft-proofing>Home & Kitchen', 34.99, 8421, 214, 7,
            12.50, 0.2500, 0.3200, 'stable', 4.4, 88,
            'ai1_passed', '{_sql_literal(features)}'::jsonb
        )
        ON CONFLICT (asin) DO UPDATE SET
            updated_at = now(),
            features = EXCLUDED.features,
            skill_score = EXCLUDED.skill_score;
        SELECT asin || '|' || skill_score::text || '|' || state::text
        FROM products_rw
        WHERE asin = '{self.asin}';
        """
        try:
            output = self._execute_sql(sql)
        except Exception as exc:
            return _failed(f"write/read cycle failed: {exc}")
        expected = f"{self.asin}|88|ai1_passed"
        if expected not in output:
            return _failed("write/read integrity mismatch", {"expected": expected, "output": output})
        return _passed("product insert and read-back verified", {"asin": self.asin})

    def restart_backend_container(self) -> ValidationStep:
        if not self.compose_file.exists():
            return _failed("production docker compose file missing", {"compose_file": str(self.compose_file)})
        command = self._compose_command("restart", self.backend_service)
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            return _failed(
                "backend container restart failed",
                {
                    "returncode": completed.returncode,
                    "stderr": completed.stderr.strip(),
                    "stdout": completed.stdout.strip(),
                },
            )
        return _passed("backend container restart completed", {"service": self.backend_service})

    def verify_read_after_restart(self) -> ValidationStep:
        try:
            output = self._execute_sql(
                f"""
                SELECT asin || '|' || skill_score::text || '|' || state::text
                FROM products_rw
                WHERE asin = '{self.asin}';
                """
            )
        except Exception as exc:
            return _failed(f"read after restart failed: {exc}")
        expected = f"{self.asin}|88|ai1_passed"
        if expected not in output:
            return _failed("product was not readable after backend restart", {"expected": expected, "output": output})
        return _passed("product persisted through backend restart", {"asin": self.asin})

    def verify_docker_volume(self) -> ValidationStep:
        if not self.compose_file.exists():
            return _failed("production docker compose file missing", {"compose_file": str(self.compose_file)})
        compose_text = self.compose_file.read_text(encoding="utf-8")
        postgres_block = _service_block(compose_text, self.postgres_service)
        volume_declared = f"{self.postgres_volume}:/var/lib/postgresql/data" in postgres_block
        named_volume_declared = f"name: {self.postgres_volume}" in compose_text
        no_ports = "ports:" not in postgres_block
        no_tmpfs = "tmpfs:" not in postgres_block
        docker_inspect = self._docker_volume_inspect()
        checks = {
            "postgres_volume_mounted": volume_declared,
            "named_volume_declared": named_volume_declared,
            "no_host_postgres_port": no_ports,
            "no_tmpfs_for_postgres": no_tmpfs,
            "docker_volume_inspect": docker_inspect.status == "PASS",
        }
        if not all(checks.values()):
            return _failed("PostgreSQL volume validation failed", {"checks": checks, "inspect": docker_inspect.to_dict()})
        return _passed("PostgreSQL named volume is stable", {"checks": checks, "inspect": docker_inspect.to_dict()})

    def cleanup_probe_row(self) -> ValidationStep:
        try:
            self._execute_sql(f"DELETE FROM products_rw WHERE asin = '{self.asin}';")
        except Exception as exc:
            return _failed(f"cleanup failed: {exc}", {"asin": self.asin})
        return _passed("persistence probe row cleaned up", {"asin": self.asin})

    def _column_names(self, table_name: str) -> list[str]:
        rows = self._execute_sql(
            f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = '{table_name}'
            ORDER BY column_name;
            """
        )
        return [line.strip() for line in rows.splitlines() if line.strip()]

    def _execute_sql(self, sql: str) -> str:
        if self.use_docker_psql:
            return self._execute_sql_via_docker(sql)
        return self._execute_sql_via_sqlalchemy(sql)

    def _execute_sql_via_sqlalchemy(self, sql: str) -> str:
        if not self.database_url.startswith("postgresql"):
            raise PersistenceValidationError("DATABASE_URL is not PostgreSQL")
        from sqlalchemy import create_engine, text

        engine = create_engine(self.database_url, pool_pre_ping=True)
        try:
            with engine.begin() as connection:
                result = connection.execute(text(sql))
                if not result.returns_rows:
                    return ""
                return "\n".join("|".join(str(value) for value in row) for row in result.fetchall())
        finally:
            engine.dispose()

    def _execute_sql_via_docker(self, sql: str) -> str:
        if not self.compose_file.exists():
            raise PersistenceValidationError("production docker compose file missing")
        command = self._compose_command(
            "exec",
            "-T",
            self.postgres_service,
            "sh",
            "-lc",
            'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -f -',
        )
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            input=sql,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            raise PersistenceValidationError(completed.stderr.strip() or completed.stdout.strip())
        return completed.stdout.strip()

    def _docker_volume_inspect(self) -> ValidationStep:
        completed = subprocess.run(
            ["docker", "volume", "inspect", self.postgres_volume],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            return _failed(
                "docker volume inspect failed",
                {"stderr": completed.stderr.strip(), "stdout": completed.stdout.strip()},
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return _failed(f"docker volume inspect returned invalid JSON: {exc}")
        if not payload:
            return _failed("docker volume inspect returned no volume records")
        return _passed("docker volume exists", {"name": self.postgres_volume})

    def _compose_command(self, *args: str) -> list[str]:
        return [*self._compose_base_command(), "-f", str(self.compose_file), *args]

    def _compose_base_command(self) -> list[str]:
        docker_compose = subprocess.run(
            ["docker", "compose", "version"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if docker_compose.returncode == 0:
            return ["docker", "compose"]
        legacy = subprocess.run(
            ["docker-compose", "version"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if legacy.returncode == 0:
            return ["docker-compose"]
        raise PersistenceValidationError(
            "Docker Compose is unavailable: "
            f"docker compose={docker_compose.stderr.strip()}; "
            f"docker-compose={legacy.stderr.strip()}"
        )


def _service_block(compose_text: str, service_name: str) -> str:
    lines = compose_text.splitlines()
    block: list[str] = []
    in_block = False
    for line in lines:
        if line.startswith(f"  {service_name}:"):
            in_block = True
            block.append(line)
            continue
        if in_block and line.startswith("  ") and not line.startswith("    "):
            break
        if in_block:
            block.append(line)
    return "\n".join(block)


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _passed(detail: str, data: dict[str, Any] | None = None) -> ValidationStep:
    return ValidationStep(status="PASS", detail=detail, data=data or {})


def _failed(detail: str, data: dict[str, Any] | None = None) -> ValidationStep:
    return ValidationStep(status="FAIL", detail=detail, data=data or {})


def _skipped(detail: str, data: dict[str, Any] | None = None) -> ValidationStep:
    return ValidationStep(status="SKIPPED", detail=detail, data=data or {})
