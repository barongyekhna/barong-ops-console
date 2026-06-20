from __future__ import annotations

from backend.app.schemas.live_gate import ApprovalUnlockDecision, CanaryRouteDecision
from backend.app.services.canary_rollout import CanaryRolloutRule, CanaryRolloutSystem
from backend.app.services.execution_unlock_flow import EXECUTION_UNLOCK_FLOW
from backend.app.services.execution_router import EXECUTION_ROUTER
from backend.app.services.live_gating_controller import (
    LiveGatePolicy,
    LiveGatingController,
)

ORG_ID = "org_11111111111111111111111111111111"
MODULE_ID = "integration.n8n_test_bridge"


def approval_unlocked() -> ApprovalUnlockDecision:
    return ApprovalUnlockDecision(
        decision="unlocked",
        approval_id="approval-live-001",
        execution_id="exec-live-001",
        unlock_id="unlock-live-001",
        unlock_token=None,
        status="approved",
        reason="approved by C12",
    )


def canary_live() -> CanaryRouteDecision:
    return CanaryRouteDecision(
        requested_mode="live",
        routed_mode="live",
        stage="live",
        percentage_rollout=100,
        org_allowed=True,
        module_allowed=True,
        org_rule_matched=True,
        module_rule_matched=True,
        deterministic_bucket=0,
        reason="test live canary",
    )


def live_policies() -> tuple[LiveGatePolicy, ...]:
    return (
        LiveGatePolicy(
            policy_scope="global",
            scope_key="live",
            enabled=True,
            staging_only=False,
        ),
        LiveGatePolicy(
            policy_scope="org",
            scope_key=ORG_ID,
            enabled=True,
            staging_only=False,
        ),
        LiveGatePolicy(
            policy_scope="module",
            scope_key=MODULE_ID,
            enabled=True,
            staging_only=False,
        ),
    )


def router_context() -> dict[str, object]:
    return {
        "org_context": {
            "org_id": ORG_ID,
            "user_id": "1",
            "role": "owner",
            "request_id": "trace-live-004",
        },
        "c18h_context_applied": True,
        "c18f_permission_decision": {
            "decision": "allow",
            "reason": "test C18F allow",
        },
        "c05_permission_result": {
            "decision": "allow",
            "reason": "test C05 allow",
            "permission_key": "modules.read",
        },
    }


def test_live_gating_controller_allows_only_after_all_live_controls_pass() -> None:
    decision = LiveGatingController(policies=live_policies()).evaluate(
        org_id=ORG_ID,
        module_id=MODULE_ID,
        requested_mode="live",
        approval=approval_unlocked(),
        canary=canary_live(),
        pre_live_validation_passed=True,
    )

    assert decision.decision == "ALLOW"
    assert decision.global_live_switch is True
    assert decision.org_policy == "enabled"
    assert decision.module_policy == "enabled"
    assert decision.c12_unlocked is True


def test_canary_rollout_defaults_live_to_staging_until_rule_matches() -> None:
    default_decision = CanaryRolloutSystem().route(
        org_id=ORG_ID,
        module_id=MODULE_ID,
        requested_mode="live",
        execution_id="exec-live-002",
    )
    allowed_decision = CanaryRolloutSystem(
        rules=(
            CanaryRolloutRule(
                scope_type="module",
                scope_key=MODULE_ID,
                stage="live",
                enabled=True,
                percentage=100,
                org_ids=(ORG_ID,),
                module_ids=(MODULE_ID,),
            ),
        )
    ).route(
        org_id=ORG_ID,
        module_id=MODULE_ID,
        requested_mode="live",
        execution_id="exec-live-002",
    )

    assert default_decision.routed_mode == "staging"
    assert default_decision.staging_only is True
    assert allowed_decision.routed_mode == "live"
    assert allowed_decision.org_allowed is True
    assert allowed_decision.module_allowed is True


def test_execution_unlock_flow_denies_live_without_db_backed_c12_token() -> None:
    result = EXECUTION_UNLOCK_FLOW.request_execution(
        org_id=ORG_ID,
        module_id=MODULE_ID,
        action="integration.n8n_test_bridge.test_run.declare",
        payload={
            "execution_mode": "live",
            "execution_id": "exec-live-003",
            "trace_id": "trace-live-003",
        },
        context={
            "org_context": {
                "org_id": ORG_ID,
                "user_id": "1",
                "role": "owner",
                "request_id": "trace-live-003",
            },
            "c18h_context_applied": True,
            "c18f_permission_decision": {
                "decision": "allow",
                "reason": "test C18F allow",
            },
            "c05_permission_result": {
                "decision": "allow",
                "reason": "test C05 allow",
                "permission_key": "modules.read",
            },
        },
        db=None,
    )

    assert result.status == "denied"
    assert result.approval.decision == "missing"
    assert result.live_gate.decision == "DENY"
    assert result.provider_router_called is False
    assert result.direct_execution_allowed is False


def test_provider_router_allows_live_plan_only_with_unlock_flow_context() -> None:
    approval = approval_unlocked()
    canary = canary_live()
    live_gate = LiveGatingController(policies=live_policies()).evaluate(
        org_id=ORG_ID,
        module_id=MODULE_ID,
        requested_mode="live",
        approval=approval,
        canary=canary,
        pre_live_validation_passed=True,
    )

    response = EXECUTION_ROUTER.receive_request(
        org_id=ORG_ID,
        module_id=MODULE_ID,
        action="integration.n8n_test_bridge.test_run.declare",
        payload={"execution_mode": "live"},
        context={
            **router_context(),
            "execution_entrypoint": "ExecutionUnlockFlow",
            "approval_unlock_decision": approval,
            "live_gate_decision": live_gate,
            "canary_decision": canary,
        },
    )

    assert response.accepted is True
    assert response.dispatch_ready is True
    assert response.execution_plan.execution_mode == "live"
    assert response.selected_provider.provider_key == "future.live_provider"
    assert response.gate_decision.live_execution_allowed is True
    assert response.live_provider_dispatched is False
    assert response.production_external_call_performed is False
