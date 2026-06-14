from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import uuid4

from sqlalchemy.orm import Session

from ..core.roles import (
    ROLE_BOT_AGENT,
    ROLE_MODULE_ADMIN,
    ROLE_SUPER_ADMIN,
    is_owner_role,
    normalize_role,
)
from ..models.approval import ApprovalDecisionRecord, ApprovalRequestRecord
from ..models.user import User
from ..repositories.approvals import (
    ApprovalRepository,
    DecisionRepository,
    WorkflowRepository,
    approval_request_from_record,
)
from ..schemas.approval import (
    C12D_APPROVAL_SAFETY_GUARANTEES,
    ApprovalActorRole,
    ApprovalActorType,
    ApprovalContextFact,
    ApprovalContextSnapshot,
    ApprovalDecision,
    ApprovalDecisionAction,
    ApprovalDecisionRecordResponse,
    ApprovalDetailResponse,
    ApprovalExecutionType,
    ApprovalListItem,
    ApprovalPermissionBoundaryResponse,
    ApprovalRequest,
    ApprovalRequestCreate,
    ApprovalRiskLevel,
    ApprovalRequestStatus,
    ApprovalSafetyBoundaryResponse,
    ApprovalWorkflow,
)
from ..schemas.common import reject_sensitive_data
from .approval_workflow_engine import (
    ApprovalWorkflowEngine,
    ApprovalWorkflowTransitionError,
)


ApprovalBoundaryAction = Literal[
    "request",
    "read",
    "list",
    "approve",
    "reject",
    "auto_approve",
]

APPROVAL_SERVICE_STAGE = "c12d_approval_persistence_api"
APPROVAL_SERVICE_SAFETY_GUARANTEES = C12D_APPROVAL_SAFETY_GUARANTEES
ADMIN_APPROVAL_ROLES = frozenset({"admin", ROLE_SUPER_ADMIN, ROLE_MODULE_ADMIN})
SYSTEM_APPROVAL_ROLES = frozenset({"system", ROLE_BOT_AGENT})
REQUESTER_ROLE_FACT_KEYS = frozenset(
    {
        "actor_role",
        "approval_actor_role",
        "requester_role",
        "role",
        "user_role",
    }
)
ROLE_ALLOWED_ACTIONS: dict[ApprovalActorRole, tuple[ApprovalBoundaryAction, ...]] = {
    "owner": ("request", "read", "list", "approve", "reject", "auto_approve"),
    "admin": ("read", "list", "approve", "reject"),
    "user": ("request",),
    "system": ("auto_approve",),
}


class ApprovalServiceError(ValueError):
    pass


class ApprovalPermissionDeniedError(ApprovalServiceError):
    pass


class ApprovalNotFoundError(ApprovalServiceError):
    pass


class ApprovalConflictError(ApprovalServiceError):
    pass


class ApprovalInvalidRequestError(ApprovalServiceError):
    pass


class ApprovalInvalidStateError(ApprovalServiceError):
    pass


@dataclass(frozen=True)
class ApprovalActor:
    user_id: int
    actor_role: ApprovalActorRole
    actor_type: ApprovalActorType
    allowed_actions: tuple[ApprovalBoundaryAction, ...]

    @property
    def full_access(self) -> bool:
        return self.actor_role == "owner"

    def permission_boundary(self) -> ApprovalPermissionBoundaryResponse:
        return ApprovalPermissionBoundaryResponse(
            actor_role=self.actor_role,
            allowed_actions=tuple(self.allowed_actions),
            full_access=self.full_access,
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def approval_actor_for_user(user: User) -> ApprovalActor:
    role = normalize_role(user.role)
    if is_owner_role(role):
        actor_role: ApprovalActorRole = "owner"
        actor_type: ApprovalActorType = "user"
    elif role in ADMIN_APPROVAL_ROLES:
        actor_role = "admin"
        actor_type = "user"
    elif role in SYSTEM_APPROVAL_ROLES:
        actor_role = "system"
        actor_type = "system"
    else:
        actor_role = "user"
        actor_type = "user"

    return ApprovalActor(
        user_id=user.id,
        actor_role=actor_role,
        actor_type=actor_type,
        allowed_actions=ROLE_ALLOWED_ACTIONS[actor_role],
    )


def _ensure_action(
    actor: ApprovalActor,
    action: ApprovalBoundaryAction,
) -> None:
    if action not in actor.allowed_actions:
        raise ApprovalPermissionDeniedError(
            f"C12 approval role '{actor.actor_role}' cannot perform '{action}'."
        )


def _safe_context_facts(
    payload: ApprovalRequestCreate,
    actor: ApprovalActor,
) -> tuple[ApprovalContextFact, ...]:
    facts: list[ApprovalContextFact] = []
    for fact in payload.context_facts:
        normalized_key = fact.key.strip().lower()
        if normalized_key in REQUESTER_ROLE_FACT_KEYS:
            raise ApprovalInvalidRequestError(
                "Approval context facts cannot override actor role."
            )
        try:
            reject_sensitive_data({fact.key: fact.value})
        except ValueError as exc:
            raise ApprovalInvalidRequestError(str(exc)) from None
        facts.append(fact)

    facts.append(
        ApprovalContextFact(
            key="requester_role",
            value=actor.actor_role,
            source="c12_approval_request",
        )
    )
    return tuple(facts)


def _source_refs(payload: ApprovalRequestCreate) -> tuple[str, ...]:
    refs = [payload.execution_id]
    refs.extend(payload.source_refs)
    deduped: list[str] = []
    for ref in refs:
        if ref not in deduped:
            deduped.append(ref)
    return tuple(deduped)


def _build_approval_request(
    payload: ApprovalRequestCreate,
    *,
    actor: ApprovalActor,
    event_time: datetime,
) -> ApprovalRequest:
    approval_id = payload.approval_id or _new_id("approval")
    snapshot = ApprovalContextSnapshot(
        snapshot_id=_new_id("approval-snapshot"),
        captured_at=event_time,
        execution_id=payload.execution_id,
        module_key=payload.module_key,
        adapter_key=payload.adapter_key,
        action_key=payload.action_key,
        requester_id=actor.user_id,
        risk_level=payload.risk_level,
        execution_type=payload.execution_type,
        source_refs=_source_refs(payload),
        facts=_safe_context_facts(payload, actor),
    )
    return ApprovalRequest(
        approval_id=approval_id,
        execution_id=payload.execution_id,
        module_key=payload.module_key,
        adapter_key=payload.adapter_key,
        action_key=payload.action_key,
        requester_id=actor.user_id,
        request_time=event_time,
        risk_level=payload.risk_level,
        execution_type=payload.execution_type,
        reason=payload.reason,
        context_snapshot=snapshot,
    )


def _decision_response(
    record: ApprovalDecisionRecord,
) -> ApprovalDecisionRecordResponse:
    return ApprovalDecisionRecordResponse(
        decision_id=record.decision_id,
        approval_id=record.approval_id,
        workflow_id=record.workflow_id,
        status=record.status,
        reason=record.reason,
        decision_source=record.decision_source,
        actor_type=record.actor_type,
        actor_role=record.actor_role,
        actor_id=record.actor_id,
        decision_time=record.decision_time,
    )


def _list_item(
    request: ApprovalRequestRecord,
    workflow: ApprovalWorkflow | None,
) -> ApprovalListItem:
    return ApprovalListItem(
        approval_id=request.approval_id,
        execution_id=request.execution_id,
        module_key=request.module_key,
        adapter_key=request.adapter_key,
        action_key=request.action_key,
        requester_id=request.requester_id,
        request_time=request.request_time,
        risk_level=cast(ApprovalRiskLevel, request.risk_level),
        execution_type=cast(ApprovalExecutionType, request.execution_type),
        status=cast(ApprovalRequestStatus, request.status),
        reviewer_id=request.reviewer_id,
        workflow_id=workflow.workflow_id if workflow is not None else None,
        workflow_state=workflow.state if workflow is not None else None,
    )


class WorkflowService:
    def __init__(
        self,
        db: Session,
        *,
        approval_repo: ApprovalRepository | None = None,
        workflow_repo: WorkflowRepository | None = None,
        decision_repo: DecisionRepository | None = None,
    ) -> None:
        self.db = db
        self.approval_repo = approval_repo or ApprovalRepository(db)
        self.workflow_repo = workflow_repo or WorkflowRepository(db)
        self.decision_repo = decision_repo or DecisionRepository(db)

    def create_workflow(
        self,
        request: ApprovalRequest,
        *,
        event_time: datetime,
    ) -> ApprovalWorkflow:
        engine = ApprovalWorkflowEngine()
        return engine.create_workflow(request, event_time=event_time)

    def save_created_workflow(
        self,
        workflow: ApprovalWorkflow,
    ) -> None:
        self.approval_repo.save(workflow.approval_request)
        self.workflow_repo.save(workflow)
        self._record_c12b_decision(workflow)

    def apply_manual_decision(
        self,
        approval_id: str,
        *,
        decision: ApprovalDecision,
        actor: ApprovalActor,
        event_time: datetime,
    ) -> ApprovalWorkflow:
        workflow = self.workflow_repo.load_by_approval_id(approval_id)
        if workflow is None:
            raise ApprovalNotFoundError(
                f"Approval workflow '{approval_id}' was not found."
            )

        engine = ApprovalWorkflowEngine()
        engine.load_workflow(workflow)
        try:
            updated = engine.apply_decision(
                decision,
                actor_id=actor.user_id,
                event_time=event_time,
            )
        except ApprovalWorkflowTransitionError as exc:
            raise ApprovalInvalidStateError(str(exc)) from None

        self.approval_repo.save(updated.approval_request)
        self.workflow_repo.save(updated)
        self.decision_repo.save(
            decision_id=_new_id("approval-decision"),
            approval_id=updated.approval_id,
            workflow_id=updated.workflow_id,
            decision=decision,
            actor_type=actor.actor_type,
            actor_role=actor.actor_role,
            actor_id=actor.user_id,
            decision_time=event_time,
        )
        return updated

    def _record_c12b_decision(
        self,
        workflow: ApprovalWorkflow,
    ) -> None:
        if not workflow.history:
            return
        entry = workflow.history[-1]
        if entry.decision_status is None or entry.decision_source is None:
            return

        decision = ApprovalDecision(
            status=entry.decision_status,
            reason=entry.reason,
            decision_source=entry.decision_source,
        )
        self.decision_repo.save(
            decision_id=_new_id("approval-decision"),
            approval_id=workflow.approval_id,
            workflow_id=workflow.workflow_id,
            decision=decision,
            actor_type="system",
            actor_role="system",
            actor_id=None,
            decision_time=entry.event_time,
        )


class ApprovalService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.approval_repo = ApprovalRepository(db)
        self.workflow_repo = WorkflowRepository(db)
        self.decision_repo = DecisionRepository(db)
        self.workflow_service = WorkflowService(
            db,
            approval_repo=self.approval_repo,
            workflow_repo=self.workflow_repo,
            decision_repo=self.decision_repo,
        )

    def request_approval(
        self,
        payload: ApprovalRequestCreate,
        *,
        user: User,
    ) -> ApprovalDetailResponse:
        actor = approval_actor_for_user(user)
        if actor.actor_role != "system":
            _ensure_action(actor, "request")

        if payload.approval_id is not None:
            existing = self.approval_repo.load_record(payload.approval_id)
            if existing is not None:
                raise ApprovalConflictError(
                    f"Approval '{payload.approval_id}' already exists."
                )
        active = self.approval_repo.find_active_by_execution_id(
            payload.execution_id
        )
        if active is not None:
            raise ApprovalConflictError(
                f"Execution '{payload.execution_id}' already has a pending approval."
            )

        event_time = _utc_now()
        request = _build_approval_request(
            payload,
            actor=actor,
            event_time=event_time,
        )
        workflow = self.workflow_service.create_workflow(
            request,
            event_time=event_time,
        )

        if actor.actor_role == "system" and workflow.state != "auto_approved":
            raise ApprovalPermissionDeniedError(
                "System approval actors may only persist auto-approved requests."
            )

        self.workflow_service.save_created_workflow(workflow)
        self.db.flush()
        return self._detail_response(
            workflow.approval_id,
            actor=actor,
            workflow=workflow,
        )

    def get_approval(
        self,
        approval_id: str,
        *,
        user: User,
    ) -> ApprovalDetailResponse:
        actor = approval_actor_for_user(user)
        _ensure_action(actor, "read")
        return self._detail_response(approval_id, actor=actor)

    def list_approvals(
        self,
        *,
        user: User,
        status: ApprovalRequestStatus | None,
        limit: int,
        offset: int,
    ) -> list[ApprovalListItem]:
        actor = approval_actor_for_user(user)
        _ensure_action(actor, "list")
        statuses = (status,) if status is not None else None
        records = self.approval_repo.query_records(
            statuses=statuses,
            limit=limit,
            offset=offset,
        )
        items: list[ApprovalListItem] = []
        for record in records:
            workflow = self.workflow_repo.load_by_approval_id(
                record.approval_id
            )
            items.append(_list_item(record, workflow))
        return items

    def approve(
        self,
        approval_id: str,
        payload: ApprovalDecisionAction,
        *,
        user: User,
    ) -> ApprovalDetailResponse:
        return self._manual_decision(
            approval_id,
            payload=payload,
            user=user,
            status="approved",
        )

    def reject(
        self,
        approval_id: str,
        payload: ApprovalDecisionAction,
        *,
        user: User,
    ) -> ApprovalDetailResponse:
        return self._manual_decision(
            approval_id,
            payload=payload,
            user=user,
            status="rejected",
        )

    def _manual_decision(
        self,
        approval_id: str,
        *,
        payload: ApprovalDecisionAction,
        user: User,
        status: Literal["approved", "rejected"],
    ) -> ApprovalDetailResponse:
        actor = approval_actor_for_user(user)
        action: ApprovalBoundaryAction = (
            "approve" if status == "approved" else "reject"
        )
        _ensure_action(actor, action)
        request = self.approval_repo.load_record(approval_id)
        if request is None:
            raise ApprovalNotFoundError(
                f"Approval '{approval_id}' was not found."
            )
        decision = ApprovalDecision(
            status=status,
            reason=payload.reason,
            decision_source="user",
        )
        workflow = self.workflow_service.apply_manual_decision(
            approval_id,
            decision=decision,
            actor=actor,
            event_time=_utc_now(),
        )
        self.db.flush()
        return self._detail_response(
            workflow.approval_id,
            actor=actor,
            workflow=workflow,
        )

    def _detail_response(
        self,
        approval_id: str,
        *,
        actor: ApprovalActor,
        workflow: ApprovalWorkflow | None = None,
    ) -> ApprovalDetailResponse:
        request_record = self.approval_repo.load_record(approval_id)
        if request_record is None:
            raise ApprovalNotFoundError(
                f"Approval '{approval_id}' was not found."
            )
        if workflow is None:
            workflow = self.workflow_repo.load_by_approval_id(approval_id)
        if workflow is None:
            raise ApprovalInvalidStateError(
                f"Approval workflow '{approval_id}' is missing."
            )
        decisions = self.decision_repo.query(
            approval_id=approval_id,
            limit=100,
            offset=0,
        )
        return ApprovalDetailResponse(
            approval=approval_request_from_record(request_record),
            workflow=workflow,
            decisions=[_decision_response(record) for record in decisions],
            permission_boundary=actor.permission_boundary(),
            safety=ApprovalSafetyBoundaryResponse(),
        )
