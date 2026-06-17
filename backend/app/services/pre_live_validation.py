from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..api.routes.health import health
from ..core.config import get_settings
from ..core.permissions import BASE_PERMISSION_REGISTRY_SEED, validate_permission_definition
from ..db.migration_safety import build_migration_safety_report
from ..db.session import engine as default_engine
from ..models.observability import AuditLogRecord, EventStreamRecord
from ..schemas.live_gate import PreLiveValidationReport, ReadinessCheckResult
from .data_isolation import current_org_data_isolation_context
from .execution_provider_registry import list_execution_provider_contracts
from .module_adapter_registry import list_adapter_contracts


class PreLiveValidationEngine:
    """Pre-live validation checklist used before live execution can unlock."""

    def __init__(
        self,
        db: Session | None = None,
        *,
        engine: Engine | None = None,
    ) -> None:
        self.db = db
        self.engine = engine or default_engine

    def run(self) -> PreLiveValidationReport:
        checks = (
            self._check_db_migration_head(),
            self._check_api_health(),
            self._check_permission_system_consistency(),
            self._check_c17_readiness(),
            self._check_execution_readiness(),
            self._check_org_isolation_correctness(),
        )
        return PreLiveValidationReport(
            passed=all(check.status == "pass" for check in checks),
            generated_at=datetime.now(UTC),
            checks=checks,
        )

    def _check_db_migration_head(self) -> ReadinessCheckResult:
        try:
            report = build_migration_safety_report(
                self.engine,
                app_env=get_settings().app_env,
            )
        except Exception as exc:
            return self._check(
                "db_migration_head",
                "fail",
                f"DB migration head check failed: {exc}",
            )
        return self._check(
            "db_migration_head",
            "pass" if report.clean else "fail",
            report.reason,
            {
                "expected_heads": report.expected_heads,
                "current_revisions": report.current_revisions,
                "production_blocked": report.production_blocked,
            },
        )

    def _check_api_health(self) -> ReadinessCheckResult:
        try:
            result = health()
        except Exception as exc:
            return self._check("api_health", "fail", f"API health check failed: {exc}")
        return self._check(
            "api_health",
            "pass" if result.status == "ok" else "fail",
            f"API health status is {result.status}.",
            result.model_dump(),
        )

    def _check_permission_system_consistency(self) -> ReadinessCheckResult:
        try:
            keys: set[str] = set()
            for permission in BASE_PERMISSION_REGISTRY_SEED:
                validated = validate_permission_definition(permission)
                key = validated["permission_key"]
                if key in keys:
                    raise ValueError(f"Duplicate permission key: {key}")
                keys.add(key)
        except Exception as exc:
            return self._check(
                "permission_system_consistency",
                "fail",
                f"Permission system consistency failed: {exc}",
            )
        return self._check(
            "permission_system_consistency",
            "pass",
            "Permission registry seed validates and has unique keys.",
            {"permission_count": len(keys)},
        )

    def _check_c17_readiness(self) -> ReadinessCheckResult:
        try:
            tables = inspect(self.engine)
            missing = [
                table
                for table in ("event_streams", "audit_logs")
                if not tables.has_table(table)
            ]
            if missing:
                return self._check(
                    "c17_readiness",
                    "fail",
                    f"C17 tables are missing: {', '.join(missing)}.",
                )
            event_columns = {
                column.name for column in EventStreamRecord.__table__.columns
            }
            audit_columns = {column.name for column in AuditLogRecord.__table__.columns}
            required = {"trace_id", "event_id", "context_id"}
            if not required.issubset(event_columns) or not required.issubset(
                audit_columns
            ):
                return self._check(
                    "c17_readiness",
                    "fail",
                    "C17 observability tables are missing required trace columns.",
                )
        except Exception as exc:
            return self._check("c17_readiness", "fail", f"C17 readiness failed: {exc}")
        return self._check(
            "c17_readiness",
            "pass",
            "C17 event_streams and audit_logs are available with trace fields.",
        )

    def _check_execution_readiness(self) -> ReadinessCheckResult:
        try:
            adapters = list_adapter_contracts()
            providers = list_execution_provider_contracts()
            if not adapters:
                raise ValueError("No C08 adapter contracts registered.")
            if not providers:
                raise ValueError("No C09 provider contracts registered.")
        except Exception as exc:
            return self._check(
                "execution_readiness",
                "fail",
                f"Execution readiness failed: {exc}",
            )
        return self._check(
            "execution_readiness",
            "pass",
            "C08 adapters and C09 provider contracts validate.",
            {"adapter_count": len(adapters), "provider_count": len(providers)},
        )

    def _check_org_isolation_correctness(self) -> ReadinessCheckResult:
        context = current_org_data_isolation_context()
        strict_context = context is not None and bool(context.org_id)
        org_columns = {
            "ops_live_gate_policies": "org_id",
            "ops_execution_unlock_tokens": "org_id",
            "ops_canary_rollouts": "org_id",
            "ops_rollback_guards": "org_id",
        }
        try:
            missing: list[str] = []
            inspector = inspect(self.engine)
            for table_name, column_name in org_columns.items():
                if not inspector.has_table(table_name):
                    missing.append(table_name)
                    continue
                columns = {
                    column["name"] for column in inspector.get_columns(table_name)
                }
                if column_name not in columns:
                    missing.append(table_name)
        except Exception as exc:
            return self._check(
                "org_isolation_correctness",
                "fail",
                f"C18 org isolation check failed: {exc}",
            )
        if missing:
            return self._check(
                "org_isolation_correctness",
                "fail",
                f"Ops live tables are missing org isolation columns: {', '.join(missing)}.",
            )
        return self._check(
            "org_isolation_correctness",
            "pass",
            "Ops live tables are org-scoped and C18 context is available when present.",
            {"strict_context_present": strict_context},
        )

    def _check(
        self,
        check: str,
        status: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> ReadinessCheckResult:
        return ReadinessCheckResult(
            check=check,
            status=status,  # type: ignore[arg-type]
            reason=reason,
            metadata=metadata or {},
        )
