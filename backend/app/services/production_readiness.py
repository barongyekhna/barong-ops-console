from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..schemas.live_gate import (
    ApprovalUnlockDecision,
    CanaryRouteDecision,
    ProductionReadinessReport,
    ReadinessCheckResult,
)
from .live_gating_controller import LiveGatingController
from .pre_live_validation import PreLiveValidationEngine

PASSING_CI_STATES = frozenset(("pass", "passed", "success", "green", "true", "1"))


class ProductionReadinessEngine:
    """Production readiness gate for enabling live execution exposure."""

    def __init__(
        self,
        db: Session | None = None,
        *,
        engine: Engine | None = None,
        ci_status: str | None = None,
    ) -> None:
        self.db = db
        self.engine = engine
        self.ci_status = ci_status

    def run(self) -> ProductionReadinessReport:
        pre_live = PreLiveValidationEngine(self.db, engine=self.engine).run()
        pre_checks = {check.check: check for check in pre_live.checks}
        checks = (
            self._check_ci_pass(),
            self._copy_check(pre_checks, "db_migration_head", "DB migration state"),
            self._copy_check(pre_checks, "api_health", "API health"),
            self._copy_check(pre_checks, "c17_readiness", "C17 system"),
            self._check_execution_gate_readiness(),
            self._copy_check(
                pre_checks,
                "org_isolation_correctness",
                "C18 isolation consistency",
            ),
        )
        return ProductionReadinessReport(
            ready=all(check.status == "pass" for check in checks),
            generated_at=datetime.now(UTC),
            checks=checks,
        )

    def _check_ci_pass(self) -> ReadinessCheckResult:
        status = (self.ci_status or os.environ.get("CI_STATUS") or "").strip().lower()
        passed = status in PASSING_CI_STATES
        return self._check(
            "ci_pass",
            "pass" if passed else "fail",
            (
                "CI status is passing."
                if passed
                else "CI pass evidence is missing or not passing."
            ),
            {"ci_status": status or "missing"},
        )

    def _check_execution_gate_readiness(self) -> ReadinessCheckResult:
        approval = ApprovalUnlockDecision(
            decision="missing",
            approval_id=None,
            execution_id="exec-readiness-check",
            unlock_id=None,
            unlock_token=None,
            status="missing",
            reason="readiness probe",
        )
        canary = CanaryRouteDecision(
            requested_mode="live",
            routed_mode="staging",
            stage="staging",
            percentage_rollout=0,
            org_allowed=False,
            module_allowed=False,
            deterministic_bucket=99,
            reason="readiness probe",
        )
        decision = LiveGatingController(global_live_switch=False).evaluate(
            org_id="org_readiness_probe",
            module_id="readiness.module",
            requested_mode="live",
            approval=approval,
            canary=canary,
            pre_live_validation_passed=False,
        )
        return self._check(
            "execution_gate_readiness",
            "pass" if decision.decision != "ALLOW" else "fail",
            (
                "Execution gate fails closed without approval, validation, and policies."
                if decision.decision != "ALLOW"
                else "Execution gate allowed live without required controls."
            ),
            {"probe_decision": decision.decision, "probe_reason": decision.reason},
        )

    def _copy_check(
        self,
        checks: dict[str, ReadinessCheckResult],
        key: str,
        label: str,
    ) -> ReadinessCheckResult:
        existing = checks.get(key)
        if existing is None:
            return self._check(
                key,
                "fail",
                f"{label} check did not run.",
            )
        return existing

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
