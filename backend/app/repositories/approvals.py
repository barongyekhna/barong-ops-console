from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.approval import (
    ApprovalDecisionRecord,
    ApprovalRequestRecord,
    ApprovalWorkflowRecord,
)
from ..schemas.approval import (
    ApprovalDecision,
    ApprovalDecisionSource,
    ApprovalDecisionStatus,
    ApprovalRequest,
    ApprovalRequestStatus,
    ApprovalWorkflow,
    ApprovalWorkflowState,
)


def _request_values(request: ApprovalRequest) -> dict[str, object]:
    payload = request.model_dump(mode="json")
    return {
        "approval_id": request.approval_id,
        "execution_id": request.execution_id,
        "module_key": request.module_key,
        "adapter_key": request.adapter_key,
        "action_key": request.action_key,
        "requester_id": request.requester_id,
        "request_time": request.request_time,
        "risk_level": request.risk_level,
        "execution_type": request.execution_type,
        "status": request.status,
        "reason": request.reason,
        "reviewer_id": request.reviewer_id,
        "context_snapshot": request.context_snapshot.model_dump(mode="json"),
        "status_trace": [
            entry.model_dump(mode="json") for entry in request.status_trace
        ],
        "request_payload": payload,
    }


def _workflow_values(workflow: ApprovalWorkflow) -> dict[str, object]:
    return {
        "workflow_id": workflow.workflow_id,
        "approval_id": workflow.approval_id,
        "execution_id": workflow.execution_id,
        "state": workflow.state,
        "workflow_created_at": workflow.created_at,
        "workflow_updated_at": workflow.updated_at,
        "workflow_payload": workflow.model_dump(mode="json"),
    }


def approval_request_from_record(
    record: ApprovalRequestRecord,
) -> ApprovalRequest:
    return ApprovalRequest.model_validate(record.request_payload)


def approval_workflow_from_record(
    record: ApprovalWorkflowRecord,
) -> ApprovalWorkflow:
    return ApprovalWorkflow.model_validate(record.workflow_payload)


class ApprovalRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save(self, request: ApprovalRequest) -> ApprovalRequestRecord:
        record = self.load_record(request.approval_id)
        values = _request_values(request)
        if record is None:
            record = ApprovalRequestRecord(**values)
        else:
            for key, value in values.items():
                setattr(record, key, value)
        self.db.add(record)
        return record

    def load(self, approval_id: str) -> ApprovalRequest | None:
        record = self.load_record(approval_id)
        if record is None:
            return None
        return approval_request_from_record(record)

    def load_record(self, approval_id: str) -> ApprovalRequestRecord | None:
        return self.db.scalar(
            select(ApprovalRequestRecord).where(
                ApprovalRequestRecord.approval_id == approval_id
            )
        )

    def find_active_by_execution_id(
        self,
        execution_id: str,
    ) -> ApprovalRequestRecord | None:
        return self.db.scalar(
            select(ApprovalRequestRecord)
            .where(ApprovalRequestRecord.execution_id == execution_id)
            .where(ApprovalRequestRecord.status == "pending")
            .order_by(ApprovalRequestRecord.id.desc())
        )

    def query(
        self,
        *,
        statuses: Sequence[ApprovalRequestStatus] | None = None,
        requester_id: int | None = None,
        limit: int,
        offset: int,
    ) -> list[ApprovalRequest]:
        return [
            approval_request_from_record(record)
            for record in self.query_records(
                statuses=statuses,
                requester_id=requester_id,
                limit=limit,
                offset=offset,
            )
        ]

    def query_records(
        self,
        *,
        statuses: Sequence[ApprovalRequestStatus] | None = None,
        requester_id: int | None = None,
        limit: int,
        offset: int,
    ) -> list[ApprovalRequestRecord]:
        statement = select(ApprovalRequestRecord)
        if statuses:
            statement = statement.where(ApprovalRequestRecord.status.in_(statuses))
        if requester_id is not None:
            statement = statement.where(
                ApprovalRequestRecord.requester_id == requester_id
            )
        statement = (
            statement.order_by(ApprovalRequestRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(statement))


class WorkflowRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save(self, workflow: ApprovalWorkflow) -> ApprovalWorkflowRecord:
        record = self.load_record(workflow.workflow_id)
        values = _workflow_values(workflow)
        if record is None:
            record = ApprovalWorkflowRecord(**values)
        else:
            for key, value in values.items():
                setattr(record, key, value)
        self.db.add(record)
        return record

    def load(self, workflow_id: str) -> ApprovalWorkflow | None:
        record = self.load_record(workflow_id)
        if record is None:
            return None
        return approval_workflow_from_record(record)

    def load_record(self, workflow_id: str) -> ApprovalWorkflowRecord | None:
        return self.db.scalar(
            select(ApprovalWorkflowRecord).where(
                ApprovalWorkflowRecord.workflow_id == workflow_id
            )
        )

    def load_by_approval_id(self, approval_id: str) -> ApprovalWorkflow | None:
        record = self.load_record_by_approval_id(approval_id)
        if record is None:
            return None
        return approval_workflow_from_record(record)

    def load_record_by_approval_id(
        self,
        approval_id: str,
    ) -> ApprovalWorkflowRecord | None:
        return self.db.scalar(
            select(ApprovalWorkflowRecord).where(
                ApprovalWorkflowRecord.approval_id == approval_id
            )
        )

    def query(
        self,
        *,
        states: Sequence[ApprovalWorkflowState] | None = None,
        approval_id: str | None = None,
        limit: int,
        offset: int,
    ) -> list[ApprovalWorkflow]:
        return [
            approval_workflow_from_record(record)
            for record in self.query_records(
                states=states,
                approval_id=approval_id,
                limit=limit,
                offset=offset,
            )
        ]

    def query_records(
        self,
        *,
        states: Sequence[ApprovalWorkflowState] | None = None,
        approval_id: str | None = None,
        limit: int,
        offset: int,
    ) -> list[ApprovalWorkflowRecord]:
        statement = select(ApprovalWorkflowRecord)
        if states:
            statement = statement.where(ApprovalWorkflowRecord.state.in_(states))
        if approval_id is not None:
            statement = statement.where(
                ApprovalWorkflowRecord.approval_id == approval_id
            )
        statement = (
            statement.order_by(ApprovalWorkflowRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(statement))


class DecisionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save(
        self,
        *,
        decision_id: str,
        approval_id: str,
        workflow_id: str,
        decision: ApprovalDecision,
        actor_type: str,
        actor_role: str,
        actor_id: int | None,
        decision_time: datetime,
    ) -> ApprovalDecisionRecord:
        record = self.load_record(decision_id)
        values = {
            "decision_id": decision_id,
            "approval_id": approval_id,
            "workflow_id": workflow_id,
            "status": decision.status,
            "reason": decision.reason,
            "decision_source": decision.decision_source,
            "actor_type": actor_type,
            "actor_role": actor_role,
            "actor_id": actor_id,
            "decision_time": decision_time,
            "decision_payload": decision.model_dump(mode="json"),
        }
        if record is None:
            record = ApprovalDecisionRecord(**values)
        else:
            for key, value in values.items():
                setattr(record, key, value)
        self.db.add(record)
        return record

    def load(self, decision_id: str) -> ApprovalDecision | None:
        record = self.load_record(decision_id)
        if record is None:
            return None
        return ApprovalDecision.model_validate(record.decision_payload)

    def load_record(self, decision_id: str) -> ApprovalDecisionRecord | None:
        return self.db.scalar(
            select(ApprovalDecisionRecord).where(
                ApprovalDecisionRecord.decision_id == decision_id
            )
        )

    def query(
        self,
        *,
        approval_id: str | None = None,
        workflow_id: str | None = None,
        statuses: Sequence[ApprovalDecisionStatus] | None = None,
        sources: Sequence[ApprovalDecisionSource] | None = None,
        limit: int,
        offset: int,
    ) -> list[ApprovalDecisionRecord]:
        statement = select(ApprovalDecisionRecord)
        if approval_id is not None:
            statement = statement.where(
                ApprovalDecisionRecord.approval_id == approval_id
            )
        if workflow_id is not None:
            statement = statement.where(
                ApprovalDecisionRecord.workflow_id == workflow_id
            )
        if statuses:
            statement = statement.where(
                ApprovalDecisionRecord.status.in_(statuses)
            )
        if sources:
            statement = statement.where(
                ApprovalDecisionRecord.decision_source.in_(sources)
            )
        statement = (
            statement.order_by(ApprovalDecisionRecord.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(statement))
