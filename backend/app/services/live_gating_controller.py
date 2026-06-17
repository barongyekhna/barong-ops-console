from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.ops import OpsLiveGatePolicyRecord
from ..schemas.live_gate import (
    ApprovalUnlockDecision,
    CanaryRouteDecision,
    LiveExecutionMode,
    LiveGateDecision,
    LiveGatePolicyInput,
    LiveGatePolicyRead,
)

PLATFORM_ORG_ID = "platform"
VALID_EXECUTION_MODES = frozenset(("mock", "staging", "live"))


@dataclass(frozen=True)
class LiveGatePolicy:
    policy_scope: str
    scope_key: str
    enabled: bool = False
    staging_only: bool = True
    rollout_percentage: int = 0
    allowed_orgs: tuple[str, ...] = ()
    allowed_modules: tuple[str, ...] = ()
    status: str = "active"

    @property
    def active(self) -> bool:
        return self.status == "active"


class LiveGatingController:
    """Final live enable gate before provider routing."""

    def __init__(
        self,
        db: Session | None = None,
        *,
        global_live_switch: bool = False,
        policies: Iterable[LiveGatePolicy] | None = None,
    ) -> None:
        self.db = db
        self.global_live_switch = global_live_switch
        self._policies = tuple(policies or ())

    def evaluate(
        self,
        *,
        org_id: str,
        module_id: str,
        requested_mode: str,
        approval: ApprovalUnlockDecision,
        canary: CanaryRouteDecision,
        pre_live_validation_passed: bool,
    ) -> LiveGateDecision:
        evaluated_at = datetime.now(UTC)
        global_switch = self._global_live_switch(org_id=org_id)
        if requested_mode not in VALID_EXECUTION_MODES:
            return self._decision(
                decision="DENY",
                reason="Execution mode is invalid.",
                requested_mode="mock",
                effective_mode="mock",
                execution_mode_valid=False,
                org_policy="not_checked",
                module_policy="not_checked",
                approval=approval,
                canary=canary,
                pre_live_validation_passed=pre_live_validation_passed,
                evaluated_at=evaluated_at,
                global_live_switch=global_switch,
            )

        mode = requested_mode  # type: ignore[assignment]
        if mode in {"mock", "staging"}:
            return self._decision(
                decision="ALLOW",
                reason=f"{mode} mode is allowed without live enablement.",
                requested_mode=mode,
                effective_mode=mode,
                execution_mode_valid=True,
                org_policy="not_required",
                module_policy="not_required",
                approval=approval,
                canary=canary,
                pre_live_validation_passed=pre_live_validation_passed,
                evaluated_at=evaluated_at,
                global_live_switch=global_switch,
            )

        org_policy = self._policy_for("org", org_id, org_id=org_id)
        module_policy = self._policy_for("module", module_id, org_id=org_id)

        if not approval.unlocked:
            return self._decision(
                decision="DENY",
                reason="Live execution requires an approved C12 unlock token.",
                requested_mode="live",
                effective_mode="live",
                execution_mode_valid=True,
                org_policy=self._policy_state(org_policy),
                module_policy=self._policy_state(module_policy),
                approval=approval,
                canary=canary,
                pre_live_validation_passed=pre_live_validation_passed,
                evaluated_at=evaluated_at,
                global_live_switch=global_switch,
            )
        if canary.routed_mode != "live":
            return self._decision(
                decision="STAGING_ONLY",
                reason="Canary routing selected staging instead of live.",
                requested_mode="live",
                effective_mode="staging",
                execution_mode_valid=True,
                org_policy=self._policy_state(org_policy),
                module_policy=self._policy_state(module_policy),
                approval=approval,
                canary=canary,
                pre_live_validation_passed=pre_live_validation_passed,
                evaluated_at=evaluated_at,
                global_live_switch=global_switch,
            )
        if not pre_live_validation_passed:
            return self._decision(
                decision="DENY",
                reason="Pre-live validation did not pass.",
                requested_mode="live",
                effective_mode="live",
                execution_mode_valid=True,
                org_policy=self._policy_state(org_policy),
                module_policy=self._policy_state(module_policy),
                approval=approval,
                canary=canary,
                pre_live_validation_passed=False,
                evaluated_at=evaluated_at,
                global_live_switch=global_switch,
            )
        if not global_switch:
            return self._decision(
                decision="STAGING_ONLY",
                reason="Global live switch is disabled; routing to staging only.",
                requested_mode="live",
                effective_mode="staging",
                execution_mode_valid=True,
                org_policy=self._policy_state(org_policy),
                module_policy=self._policy_state(module_policy),
                approval=approval,
                canary=canary,
                pre_live_validation_passed=pre_live_validation_passed,
                evaluated_at=evaluated_at,
                global_live_switch=global_switch,
            )
        if org_policy is None or not org_policy.active or not org_policy.enabled:
            return self._decision(
                decision="DENY",
                reason="No active org live policy enables this org.",
                requested_mode="live",
                effective_mode="live",
                execution_mode_valid=True,
                org_policy=self._policy_state(org_policy),
                module_policy=self._policy_state(module_policy),
                approval=approval,
                canary=canary,
                pre_live_validation_passed=pre_live_validation_passed,
                evaluated_at=evaluated_at,
                global_live_switch=global_switch,
            )
        if module_policy is None or not module_policy.active or not module_policy.enabled:
            return self._decision(
                decision="DENY",
                reason="No active module live policy enables this module.",
                requested_mode="live",
                effective_mode="live",
                execution_mode_valid=True,
                org_policy=self._policy_state(org_policy),
                module_policy=self._policy_state(module_policy),
                approval=approval,
                canary=canary,
                pre_live_validation_passed=pre_live_validation_passed,
                evaluated_at=evaluated_at,
                global_live_switch=global_switch,
            )
        if org_policy.staging_only or module_policy.staging_only:
            return self._decision(
                decision="STAGING_ONLY",
                reason="Org or module policy is staging-only.",
                requested_mode="live",
                effective_mode="staging",
                execution_mode_valid=True,
                org_policy=self._policy_state(org_policy),
                module_policy=self._policy_state(module_policy),
                approval=approval,
                canary=canary,
                pre_live_validation_passed=pre_live_validation_passed,
                evaluated_at=evaluated_at,
                global_live_switch=global_switch,
            )

        return self._decision(
            decision="ALLOW",
            reason="Global, org, module, approval, validation, and canary gates allow live.",
            requested_mode="live",
            effective_mode="live",
            execution_mode_valid=True,
            org_policy=self._policy_state(org_policy),
            module_policy=self._policy_state(module_policy),
            approval=approval,
            canary=canary,
            pre_live_validation_passed=pre_live_validation_passed,
            evaluated_at=evaluated_at,
            global_live_switch=global_switch,
        )

    def upsert_policy(
        self,
        *,
        org_id: str,
        payload: LiveGatePolicyInput,
    ) -> LiveGatePolicyRead:
        if self.db is None:
            raise ValueError("Live gate policy persistence requires a database session.")
        record = self.db.scalar(
            select(OpsLiveGatePolicyRecord).where(
                OpsLiveGatePolicyRecord.org_id == org_id,
                OpsLiveGatePolicyRecord.policy_scope == payload.policy_scope,
                OpsLiveGatePolicyRecord.scope_key == payload.scope_key,
            )
        )
        if record is None:
            record = OpsLiveGatePolicyRecord(
                org_id=org_id,
                policy_id=f"live-policy-{uuid4()}",
                policy_scope=payload.policy_scope,
                scope_key=payload.scope_key,
                enabled=payload.enabled,
                staging_only=payload.staging_only,
                rollout_percentage=payload.rollout_percentage,
                allowed_orgs=list(payload.allowed_orgs),
                allowed_modules=list(payload.allowed_modules),
                status=payload.status,
                metadata_json=payload.metadata,
            )
        else:
            record.enabled = payload.enabled
            record.staging_only = payload.staging_only
            record.rollout_percentage = payload.rollout_percentage
            record.allowed_orgs = list(payload.allowed_orgs)
            record.allowed_modules = list(payload.allowed_modules)
            record.status = payload.status
            record.metadata_json = payload.metadata
        self.db.add(record)
        self.db.flush()
        return self._read_policy(record)

    def list_policies(self, *, org_id: str) -> list[LiveGatePolicyRead]:
        if self.db is None:
            return [
                LiveGatePolicyRead(
                    policy_id=f"memory-{index}",
                    org_id=org_id,
                    policy_scope=policy.policy_scope,  # type: ignore[arg-type]
                    scope_key=policy.scope_key,
                    enabled=policy.enabled,
                    staging_only=policy.staging_only,
                    rollout_percentage=policy.rollout_percentage,
                    allowed_orgs=policy.allowed_orgs,
                    allowed_modules=policy.allowed_modules,
                    status=policy.status,  # type: ignore[arg-type]
                    metadata={},
                )
                for index, policy in enumerate(self._policies)
            ]
        rows = list(
            self.db.scalars(
                select(OpsLiveGatePolicyRecord)
                .where(OpsLiveGatePolicyRecord.org_id.in_((org_id, PLATFORM_ORG_ID)))
                .order_by(OpsLiveGatePolicyRecord.id.asc())
            )
        )
        return [self._read_policy(row) for row in rows]

    def _global_live_switch(self, *, org_id: str) -> bool:
        policy = self._policy_for("global", "live", org_id=org_id)
        if policy is not None and policy.active:
            return policy.enabled and not policy.staging_only
        return self.global_live_switch

    def _policy_for(
        self,
        policy_scope: str,
        scope_key: str,
        *,
        org_id: str,
    ) -> LiveGatePolicy | None:
        for policy in self._policies:
            if policy.policy_scope == policy_scope and policy.scope_key == scope_key:
                return policy
        if self.db is None:
            return None
        rows = list(
            self.db.scalars(
                select(OpsLiveGatePolicyRecord)
                .where(
                    OpsLiveGatePolicyRecord.org_id.in_((org_id, PLATFORM_ORG_ID)),
                    OpsLiveGatePolicyRecord.policy_scope == policy_scope,
                    OpsLiveGatePolicyRecord.scope_key == scope_key,
                    OpsLiveGatePolicyRecord.status == "active",
                )
                .order_by(OpsLiveGatePolicyRecord.id.desc())
            )
        )
        row = next((candidate for candidate in rows if candidate.org_id == org_id), None)
        if row is None and rows:
            row = rows[0]
        if row is None:
            return None
        return LiveGatePolicy(
            policy_scope=row.policy_scope,
            scope_key=row.scope_key,
            enabled=row.enabled,
            staging_only=row.staging_only,
            rollout_percentage=row.rollout_percentage,
            allowed_orgs=tuple(row.allowed_orgs or ()),
            allowed_modules=tuple(row.allowed_modules or ()),
            status=row.status,
        )

    def _policy_state(self, policy: LiveGatePolicy | None) -> str:
        if policy is None:
            return "missing"
        if not policy.active:
            return "disabled"
        if policy.staging_only:
            return "staging_only"
        if policy.enabled:
            return "enabled"
        return "disabled"

    def _decision(
        self,
        *,
        decision: str,
        reason: str,
        requested_mode: LiveExecutionMode,
        effective_mode: LiveExecutionMode,
        execution_mode_valid: bool,
        org_policy: str,
        module_policy: str,
        approval: ApprovalUnlockDecision,
        canary: CanaryRouteDecision,
        pre_live_validation_passed: bool,
        evaluated_at: datetime,
        global_live_switch: bool,
    ) -> LiveGateDecision:
        return LiveGateDecision(
            decision=decision,  # type: ignore[arg-type]
            reason=reason,
            execution_mode_requested=requested_mode,
            execution_mode_effective=effective_mode,
            execution_mode_valid=execution_mode_valid,
            global_live_switch=global_live_switch,
            org_policy_checked=org_policy != "not_checked",
            org_policy=org_policy,
            module_policy_checked=module_policy != "not_checked",
            module_policy=module_policy,
            c12_unlock_required=requested_mode == "live",
            c12_unlocked=approval.unlocked,
            pre_live_validation_passed=pre_live_validation_passed,
            canary_stage=canary.stage,
            evaluated_at=evaluated_at,
        )

    def _read_policy(self, record: OpsLiveGatePolicyRecord) -> LiveGatePolicyRead:
        return LiveGatePolicyRead(
            policy_id=record.policy_id,
            org_id=record.org_id,
            policy_scope=record.policy_scope,  # type: ignore[arg-type]
            scope_key=record.scope_key,
            enabled=record.enabled,
            staging_only=record.staging_only,
            rollout_percentage=record.rollout_percentage,
            allowed_orgs=tuple(record.allowed_orgs or ()),
            allowed_modules=tuple(record.allowed_modules or ()),
            status=record.status,  # type: ignore[arg-type]
            metadata=dict(record.metadata_json or {}),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
