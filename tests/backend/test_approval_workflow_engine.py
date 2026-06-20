from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.app.schemas.approval import (
    ApprovalContextFact,
    ApprovalContextSnapshot,
    ApprovalDecision,
    ApprovalExecutionType,
    ApprovalRequest,
    ApprovalRiskLevel,
)
from backend.app.services.approval_workflow_engine import (
    ApprovalWorkflowEngine,
    ApprovalWorkflowTransitionError,
)


NOW = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 6, 14, 12, 5, tzinfo=UTC)


def approval_request(
    *,
    approval_id: str = "approval-1",
    execution_id: str = "execution-1",
    module_key: str = "admin.users",
    requester_role: str = "non_owner",
    risk_level: ApprovalRiskLevel = "high",
    execution_type: ApprovalExecutionType = "real",
) -> ApprovalRequest:
    snapshot = ApprovalContextSnapshot(
        snapshot_id=f"snapshot-{approval_id}",
        captured_at=NOW,
        execution_id=execution_id,
        module_key=module_key,
        adapter_key="admin.users.adapter",
        action_key="admin.users.manage",
        requester_id=1,
        risk_level=risk_level,
        execution_type=execution_type,
        source_refs=(execution_id,),
        facts=(
            ApprovalContextFact(
                key="requester_role",
                value=requester_role,
                source="c12_approval_request",
            ),
        ),
    )
    return ApprovalRequest(
        approval_id=approval_id,
        execution_id=execution_id,
        module_key=module_key,
        adapter_key="admin.users.adapter",
        action_key="admin.users.manage",
        requester_id=1,
        request_time=NOW,
        risk_level=risk_level,
        execution_type=execution_type,
        reason="Approval is required before execution can continue.",
        context_snapshot=snapshot,
    )


def test_create_workflow_auto_applies_c12b_decision() -> None:
    engine = ApprovalWorkflowEngine()

    workflow = engine.create_workflow(
        approval_request(
            module_key="business.products",
            requester_role="owner",
            risk_level="low",
            execution_type="mock",
        ),
        event_time=NOW,
    )

    assert workflow.state == "auto_approved"
    assert workflow.approval_request.status == "auto_approved"
    assert [entry.event for entry in workflow.history] == [
        "execution_request_triggered",
        "workflow_state_updated",
    ]
    assert workflow.history[-1].decision_source == "user"
    assert [
        entry.event for entry in workflow.approval_request.status_trace
    ] == [
        "request_created",
        "auto_approved",
    ]
    assert workflow.approval_request.status_trace[-1].decision_source == "user"


def test_create_workflow_records_pending_decision_without_state_change() -> None:
    engine = ApprovalWorkflowEngine()

    workflow = engine.create_workflow(
        approval_request(),
        event_time=NOW,
    )

    assert workflow.state == "pending"
    assert workflow.approval_request.status == "pending"
    assert [entry.event for entry in workflow.history] == [
        "execution_request_triggered",
        "c12b_decision_recorded",
    ]
    assert workflow.history[-1].state_changed is False
    assert workflow.history[-1].decision_status == "pending"
    assert workflow.history[-1].decision_source == "user"
    assert len(workflow.approval_request.status_trace) == 1


def test_manual_decision_uses_state_machine_and_reviewer() -> None:
    engine = ApprovalWorkflowEngine()
    engine.create_workflow(approval_request(), event_time=NOW)

    workflow = engine.apply_decision(
        ApprovalDecision(
            status="approved",
            reason="Owner approved the pending execution request.",
            decision_source="user",
        ),
        actor_id=42,
        event_time=LATER,
    )

    assert workflow.state == "approved"
    assert workflow.approval_request.status == "approved"
    assert workflow.approval_request.reviewer_id == 42
    assert workflow.history[-1].event == "workflow_state_updated"
    assert workflow.history[-1].decision_source == "user"
    assert workflow.approval_request.status_trace[-1].event == "manual_approved"
    assert workflow.approval_request.status_trace[-1].actor_id == 42


def test_update_state_requires_matching_decision() -> None:
    engine = ApprovalWorkflowEngine()
    engine.create_workflow(approval_request(), event_time=NOW)

    with pytest.raises(
        ApprovalWorkflowTransitionError,
        match="state transitions require a decision",
    ):
        engine.update_state("approved", event_time=LATER)

    with pytest.raises(
        ApprovalWorkflowTransitionError,
        match="decision status must match target workflow state",
    ):
        engine.update_state(
            "approved",
            decision=ApprovalDecision(
                status="rejected",
                reason="Decision does not match target state.",
                decision_source="user",
            ),
            event_time=LATER,
        )


def test_terminal_workflow_rejects_new_decision() -> None:
    engine = ApprovalWorkflowEngine()
    engine.create_workflow(approval_request(), event_time=NOW)
    engine.apply_decision(
        ApprovalDecision(
            status="rejected",
            reason="Rejected after review.",
            decision_source="user",
        ),
        actor_id=42,
        event_time=LATER,
    )

    with pytest.raises(
        ApprovalWorkflowTransitionError,
        match="Terminal approval workflows cannot accept new decisions.",
    ):
        engine.apply_decision(
            ApprovalDecision(
                status="approved",
                reason="Attempt to change a terminal decision.",
                decision_source="user",
            ),
            actor_id=42,
            event_time=LATER,
        )


def test_identity_drift_is_rejected_by_c12b_on_create() -> None:
    engine = ApprovalWorkflowEngine()
    request = approval_request(
        module_key="admin.users",
        risk_level="low",
        execution_type="mock",
    )
    drifted_snapshot = request.context_snapshot.model_copy(
        update={"module_key": "business.changed"}
    )
    drifted_request = request.model_copy(
        update={"context_snapshot": drifted_snapshot}
    )

    workflow = engine.create_workflow(drifted_request, event_time=NOW)

    assert workflow.state == "rejected"
    assert workflow.approval_request.status == "rejected"
    assert workflow.history[-1].decision_source == "global"
    assert (
        workflow.approval_request.status_trace[-1].decision_source == "global"
    )
