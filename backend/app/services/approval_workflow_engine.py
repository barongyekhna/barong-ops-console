from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from ..schemas.approval import (
    APPROVAL_REQUEST_INITIAL_STATUS,
    APPROVAL_REQUEST_TERMINAL_STATUSES,
    APPROVAL_WORKFLOW_ALLOWED_TRANSITIONS,
    APPROVAL_WORKFLOW_INITIAL_STATE,
    ApprovalDecision,
    ApprovalRequest,
    ApprovalRequestStatus,
    ApprovalStatusTraceEntry,
    ApprovalStatusTransitionEvent,
    ApprovalWorkflow,
    ApprovalWorkflowHistoryEntry,
    ApprovalWorkflowState,
)
from .approval_rule_engine import ApprovalRuleEngine, approval_rule_engine


APPROVAL_WORKFLOW_ENGINE_STAGE = "c12c_approval_workflow_engine"
APPROVAL_WORKFLOW_ENGINE_SAFETY_GUARANTEES = (
    "ApprovalWorkflowEngine only creates in-memory workflow state.",
    "ApprovalWorkflowEngine applies ApprovalDecision data and does not execute actions.",
    "ApprovalWorkflowEngine does not call C09 execution provider APIs.",
    "ApprovalWorkflowEngine does not call C10 sandbox runtime or bridge.",
    "ApprovalWorkflowEngine does not write database rows or operation logs.",
    "ApprovalWorkflowEngine does not call external APIs or provider endpoints.",
)

APPROVAL_WORKFLOW_STATES = frozenset(
    {
        "pending",
        "approved",
        "rejected",
        "auto_approved",
    }
)


class ApprovalWorkflowTransitionError(ValueError):
    """Raised when an approval workflow state transition is not allowed."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _approval_request_from_raw(
    request: ApprovalRequest | Mapping[str, Any],
) -> ApprovalRequest:
    if isinstance(request, ApprovalRequest):
        return request
    return ApprovalRequest.model_validate(request)


def _approval_decision_from_raw(
    decision: ApprovalDecision | Mapping[str, Any],
) -> ApprovalDecision:
    if isinstance(decision, ApprovalDecision):
        return decision
    return ApprovalDecision.model_validate(decision)


def _workflow_id(request: ApprovalRequest) -> str:
    return f"approval-workflow:{request.approval_id}"


def _status_event_for_state(
    state: ApprovalRequestStatus,
) -> ApprovalStatusTransitionEvent:
    if state == "approved":
        return "manual_approved"
    if state == "rejected":
        return "manual_rejected"
    if state == "auto_approved":
        return "auto_approved"
    return "request_created"


def _ensure_known_state(state: str) -> ApprovalWorkflowState:
    if state not in APPROVAL_WORKFLOW_STATES:
        raise ApprovalWorkflowTransitionError(
            f"Unknown approval workflow state: {state}."
        )
    return cast(ApprovalWorkflowState, state)


class ApprovalWorkflowEngine:
    def __init__(
        self,
        rule_engine: ApprovalRuleEngine | None = None,
    ) -> None:
        self.rule_engine = rule_engine or approval_rule_engine
        self._workflow: ApprovalWorkflow | None = None

    @property
    def workflow(self) -> ApprovalWorkflow | None:
        return self._workflow

    def create_workflow(
        self,
        request: ApprovalRequest | Mapping[str, Any],
        *,
        event_time: datetime | None = None,
    ) -> ApprovalWorkflow:
        approval_request = _approval_request_from_raw(request)
        if approval_request.status != APPROVAL_REQUEST_INITIAL_STATUS:
            raise ApprovalWorkflowTransitionError(
                "New approval workflows must start from pending request status."
            )

        now = event_time or _utc_now()
        request_with_trace = self._append_status_trace(
            approval_request,
            from_state=None,
            to_state=APPROVAL_WORKFLOW_INITIAL_STATE,
            reason="Execution request triggered C12 approval workflow.",
            event_time=now,
            decision=None,
            actor_id=None,
        )
        history = (
            ApprovalWorkflowHistoryEntry(
                event="execution_request_triggered",
                from_state=None,
                to_state=APPROVAL_WORKFLOW_INITIAL_STATE,
                state_changed=True,
                event_time=now,
                reason="Execution request triggered C12 approval workflow.",
            ),
        )
        self._workflow = ApprovalWorkflow(
            workflow_id=_workflow_id(request_with_trace),
            approval_id=request_with_trace.approval_id,
            execution_id=request_with_trace.execution_id,
            state=APPROVAL_WORKFLOW_INITIAL_STATE,
            approval_request=request_with_trace,
            created_at=now,
            updated_at=now,
            history=history,
        )

        c12b_decision = self.rule_engine.evaluate(request_with_trace)
        return self.apply_decision(c12b_decision, event_time=now)

    def apply_decision(
        self,
        decision: ApprovalDecision | Mapping[str, Any],
        *,
        actor_id: int | None = None,
        event_time: datetime | None = None,
    ) -> ApprovalWorkflow:
        workflow = self._require_workflow()
        if workflow.state in APPROVAL_REQUEST_TERMINAL_STATUSES:
            raise ApprovalWorkflowTransitionError(
                "Terminal approval workflows cannot accept new decisions."
            )

        approval_decision = _approval_decision_from_raw(decision)
        if approval_decision.status == "pending":
            return self.update_state(
                workflow.state,
                decision=approval_decision,
                actor_id=actor_id,
                event_time=event_time,
                allow_noop=True,
            )

        return self.update_state(
            approval_decision.status,
            decision=approval_decision,
            actor_id=actor_id,
            event_time=event_time,
        )

    def update_state(
        self,
        target_state: ApprovalWorkflowState | str,
        *,
        decision: ApprovalDecision | Mapping[str, Any] | None = None,
        actor_id: int | None = None,
        event_time: datetime | None = None,
        allow_noop: bool = False,
    ) -> ApprovalWorkflow:
        workflow = self._require_workflow()
        state = _ensure_known_state(target_state)
        approval_decision = (
            _approval_decision_from_raw(decision)
            if decision is not None
            else None
        )
        if approval_decision is not None and approval_decision.status != state:
            raise ApprovalWorkflowTransitionError(
                "Approval decision status must match target workflow state."
            )
        now = event_time or _utc_now()

        if workflow.state == state:
            if not allow_noop:
                raise ApprovalWorkflowTransitionError(
                    f"Approval workflow is already in state {state}."
                )
            return self._record_decision_without_state_change(
                workflow,
                decision=approval_decision,
                actor_id=actor_id,
                event_time=now,
            )

        if workflow.state in APPROVAL_REQUEST_TERMINAL_STATUSES:
            raise ApprovalWorkflowTransitionError(
                "Terminal approval workflow states cannot transition."
            )

        transition = (workflow.state, state)
        if transition not in APPROVAL_WORKFLOW_ALLOWED_TRANSITIONS:
            raise ApprovalWorkflowTransitionError(
                f"Invalid approval workflow transition: {workflow.state} -> {state}."
            )
        if approval_decision is None:
            raise ApprovalWorkflowTransitionError(
                "Approval workflow state transitions require a decision."
            )

        request = self._append_status_trace(
            workflow.approval_request,
            from_state=workflow.state,
            to_state=state,
            reason=approval_decision.reason,
            event_time=now,
            decision=approval_decision,
            actor_id=actor_id,
        )
        request = request.model_copy(
            update={
                "status": state,
                "reviewer_id": self._reviewer_id_for_state(
                    state,
                    current_reviewer_id=request.reviewer_id,
                    actor_id=actor_id,
                ),
            }
        )
        history = workflow.history + (
            ApprovalWorkflowHistoryEntry(
                event="workflow_state_updated",
                from_state=workflow.state,
                to_state=state,
                state_changed=True,
                event_time=now,
                decision_status=approval_decision.status,
                decision_source=approval_decision.decision_source,
                actor_id=actor_id,
                reason=approval_decision.reason,
            ),
        )
        self._workflow = workflow.model_copy(
            update={
                "state": state,
                "approval_request": request,
                "updated_at": now,
                "history": history,
            }
        )
        return self._workflow

    def _require_workflow(self) -> ApprovalWorkflow:
        if self._workflow is None:
            raise ApprovalWorkflowTransitionError(
                "Approval workflow has not been created."
            )
        return self._workflow

    def _record_decision_without_state_change(
        self,
        workflow: ApprovalWorkflow,
        *,
        decision: ApprovalDecision | None,
        actor_id: int | None,
        event_time: datetime,
    ) -> ApprovalWorkflow:
        if decision is None:
            raise ApprovalWorkflowTransitionError(
                "No-op approval workflow updates require a decision."
            )
        history = workflow.history + (
            ApprovalWorkflowHistoryEntry(
                event="c12b_decision_recorded",
                from_state=workflow.state,
                to_state=workflow.state,
                state_changed=False,
                event_time=event_time,
                decision_status=decision.status,
                decision_source=decision.decision_source,
                actor_id=actor_id,
                reason=decision.reason,
            ),
        )
        self._workflow = workflow.model_copy(
            update={
                "updated_at": event_time,
                "history": history,
            }
        )
        return self._workflow

    def _append_status_trace(
        self,
        request: ApprovalRequest,
        *,
        from_state: ApprovalWorkflowState | None,
        to_state: ApprovalWorkflowState,
        reason: str,
        event_time: datetime,
        decision: ApprovalDecision | None,
        actor_id: int | None,
    ) -> ApprovalRequest:
        trace = request.status_trace + (
            ApprovalStatusTraceEntry(
                event=_status_event_for_state(to_state),
                from_status=from_state,
                to_status=to_state,
                actor_id=actor_id,
                transition_time=event_time,
                reason=reason,
                decision_source=(
                    decision.decision_source if decision is not None else None
                ),
            ),
        )
        return request.model_copy(update={"status_trace": trace})

    def _reviewer_id_for_state(
        self,
        state: ApprovalWorkflowState,
        *,
        current_reviewer_id: int | None,
        actor_id: int | None,
    ) -> int | None:
        if state in {"approved", "rejected"}:
            return actor_id or current_reviewer_id
        return current_reviewer_id
