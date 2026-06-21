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
from ..repositories.tenant import tenant_org_id_for_create
from ..repositories.approvals import (
    ApprovalRepository,
    DecisionRepository,
    WorkflowRepository,
    approval_request_from_record,
    decode_approval_request_cursor,
    encode_approval_request_cursor,
)
from ..schemas.approval import (
    C12D_APPROVAL_SAFETY_GUARANTEES,
    ApprovalActorRole,
    ApprovalActorType,
    ApprovalCategory,
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
from ..schemas.storage_layer import StorageRecordEnvelope
from .auth_service import AuditContext
from .audit_query_engine import AuditLogWriter
from .approval_workflow_engine import (
    ApprovalWorkflowEngine,
    ApprovalWorkflowTransitionError,
)
from .approval_productization import (
    CONTROL_PLANE_CATEGORY,
    FEATURE_CATEGORY,
    approval_category_from_keys,
    approval_display_info,
    module_key_matches_permission_tokens,
    module_permission_tokens,
)
from .c12_approval_unlock import C12ApprovalUnlockTokenController
from .permission_service import resolve_effective_permissions


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
    "user": ("request", "read", "list"),
    "system": ("auto_approve",),
}
APPROVAL_LIST_DEFAULT_LIMIT = 50
APPROVAL_LIST_MAX_LIMIT = 100
APPROVAL_REJECT_REASON_MIN_LENGTH = 15
APPROVAL_APPROVE_DEFAULT_REASON = "审批人已同意该申请。"


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


@dataclass(frozen=True)
class ApprovalListVisibility:
    categories: tuple[ApprovalCategory, ...] | None
    permission_keys: frozenset[str] | None = None
    module_tokens: frozenset[str] | None = None
    empty: bool = False


@dataclass(frozen=True)
class ApprovalListPage:
    items: list[ApprovalListItem]
    next_cursor: str | None


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


def _approval_category(payload: ApprovalRequestCreate) -> ApprovalCategory:
    return approval_category_from_keys(
        module_key=payload.module_key,
        action_key=payload.action_key,
        adapter_key=payload.adapter_key,
        explicit_category=payload.category,
    )


def _ensure_category_request_allowed(
    actor: ApprovalActor,
    category: ApprovalCategory,
) -> None:
    if category == CONTROL_PLANE_CATEGORY and actor.actor_role not in {
        "owner",
        "system",
    }:
        raise ApprovalPermissionDeniedError(
            "主控审批仅允许 owner 创建或处理。"
        )


def _build_approval_request(
    payload: ApprovalRequestCreate,
    *,
    actor: ApprovalActor,
    event_time: datetime,
    organization_id: str,
    category: ApprovalCategory,
) -> ApprovalRequest:
    approval_id = payload.approval_id or _new_id("approval")
    snapshot = ApprovalContextSnapshot(
        snapshot_id=_new_id("approval-snapshot"),
        captured_at=event_time,
        execution_id=payload.execution_id,
        organization_id=organization_id,
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
        organization_id=organization_id,
        module_key=payload.module_key,
        adapter_key=payload.adapter_key,
        action_key=payload.action_key,
        requester_id=actor.user_id,
        request_time=event_time,
        risk_level=payload.risk_level,
        execution_type=payload.execution_type,
        category=category,
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
    category = approval_category_from_keys(
        module_key=request.module_key,
        action_key=request.action_key,
        adapter_key=request.adapter_key,
        explicit_category=getattr(request, "category", None),
    )
    return ApprovalListItem(
        approval_id=request.approval_id,
        execution_id=request.execution_id,
        organization_id=request.org_id,
        module_key=request.module_key,
        adapter_key=request.adapter_key,
        action_key=request.action_key,
        requester_id=request.requester_id,
        request_time=request.request_time,
        risk_level=cast(ApprovalRiskLevel, request.risk_level),
        execution_type=cast(ApprovalExecutionType, request.execution_type),
        category=category,
        status=cast(ApprovalRequestStatus, request.status),
        reviewer_id=request.reviewer_id,
        workflow_id=workflow.workflow_id if workflow is not None else None,
        workflow_state=workflow.state if workflow is not None else None,
        display=approval_display_info(
            module_key=request.module_key,
            action_key=request.action_key,
            category=category,
            status=request.status,
            risk_level=request.risk_level,
        ),
    )


def _record_category(record: ApprovalRequestRecord) -> ApprovalCategory:
    return approval_category_from_keys(
        module_key=record.module_key,
        action_key=record.action_key,
        adapter_key=record.adapter_key,
        explicit_category=getattr(record, "category", None),
    )


def _scoped_permission_keys_for_user(db: Session, user: User) -> set[str]:
    effective = resolve_effective_permissions(db, user)
    if effective.is_owner_full_access:
        return {"*"}
    return set(effective.permissions)


def _module_visible_to_employee(
    db: Session,
    *,
    user: User,
    module_key: str,
    permission_keys: set[str] | None = None,
) -> bool:
    if permission_keys is None:
        permission_keys = _scoped_permission_keys_for_user(db, user)
    if "*" in permission_keys:
        return True
    tokens = module_permission_tokens(permission_keys)
    return module_key_matches_permission_tokens(module_key, tokens)


def _record_visible_to_actor(
    db: Session,
    *,
    user: User,
    actor: ApprovalActor,
    record: ApprovalRequestRecord,
    permission_keys: set[str] | None = None,
) -> bool:
    if actor.actor_role == "system":
        return True
    category = _record_category(record)
    if category == CONTROL_PLANE_CATEGORY:
        return actor.actor_role == "owner"
    if actor.actor_role in {"owner", "admin"}:
        return True
    return _module_visible_to_employee(
        db,
        user=user,
        module_key=record.module_key,
        permission_keys=permission_keys,
    )


def _ensure_record_visible(
    db: Session,
    *,
    user: User,
    actor: ApprovalActor,
    record: ApprovalRequestRecord,
) -> None:
    if not _record_visible_to_actor(db, user=user, actor=actor, record=record):
        raise ApprovalPermissionDeniedError("当前用户不能查看该审批。")


def _decision_reason(
    payload: ApprovalDecisionAction,
    *,
    status: Literal["approved", "rejected"],
) -> str:
    reason = payload.reason.strip()
    if status == "rejected":
        if len(reason) < APPROVAL_REJECT_REASON_MIN_LENGTH:
            raise ApprovalInvalidRequestError(
                "拒绝原因至少需要 15 个字符。"
            )
        return reason
    return reason or APPROVAL_APPROVE_DEFAULT_REASON


def _audit_status(status: Literal["approved", "rejected"]) -> Literal["success", "failed"]:
    return "success" if status == "approved" else "failed"


def _approval_list_visibility(
    db: Session,
    *,
    user: User,
    actor: ApprovalActor,
    category: ApprovalCategory | None,
) -> ApprovalListVisibility:
    if actor.actor_role == "system":
        return ApprovalListVisibility(
            categories=(category,) if category is not None else None,
        )
    if actor.actor_role == "owner":
        return ApprovalListVisibility(
            categories=(category,) if category is not None else None,
        )
    if actor.actor_role == "admin":
        if category == CONTROL_PLANE_CATEGORY:
            return ApprovalListVisibility(categories=(), empty=True)
        return ApprovalListVisibility(categories=(FEATURE_CATEGORY,))

    if category == CONTROL_PLANE_CATEGORY:
        return ApprovalListVisibility(categories=(), empty=True)

    permission_keys = frozenset(_scoped_permission_keys_for_user(db, user))
    if "*" in permission_keys:
        return ApprovalListVisibility(
            categories=(FEATURE_CATEGORY,),
            permission_keys=permission_keys,
        )

    module_tokens = frozenset(module_permission_tokens(permission_keys))
    if not module_tokens:
        return ApprovalListVisibility(
            categories=(FEATURE_CATEGORY,),
            permission_keys=permission_keys,
            module_tokens=module_tokens,
            empty=True,
        )
    return ApprovalListVisibility(
        categories=(FEATURE_CATEGORY,),
        permission_keys=permission_keys,
        module_tokens=module_tokens,
    )


def _record_matches_visibility(
    record: ApprovalRequestRecord,
    visibility: ApprovalListVisibility,
) -> bool:
    if visibility.empty:
        return False
    if visibility.module_tokens is None or "*" in (visibility.permission_keys or ()):
        return True
    return module_key_matches_permission_tokens(
        record.module_key,
        visibility.module_tokens,
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
        category = _approval_category(payload)
        _ensure_category_request_allowed(actor, category)
        if (
            actor.actor_role == "user"
            and category == FEATURE_CATEGORY
            and not _module_visible_to_employee(
                self.db,
                user=user,
                module_key=payload.module_key,
            )
        ):
            raise ApprovalPermissionDeniedError("当前用户不能创建该模块审批。")

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
        organization_id = tenant_org_id_for_create()
        request = _build_approval_request(
            payload,
            actor=actor,
            event_time=event_time,
            organization_id=organization_id,
            category=category,
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
        execution_unlock = self._sync_unlock_binding(
            workflow.approval_id,
            reveal_token=workflow.state in {"approved", "auto_approved"},
        )
        return self._detail_response(
            workflow.approval_id,
            actor=actor,
            user=user,
            workflow=workflow,
            execution_unlock=execution_unlock,
        )

    def get_approval(
        self,
        approval_id: str,
        *,
        user: User,
    ) -> ApprovalDetailResponse:
        actor = approval_actor_for_user(user)
        _ensure_action(actor, "read")
        return self._detail_response(approval_id, actor=actor, user=user)

    def list_approvals(
        self,
        *,
        user: User,
        status: ApprovalRequestStatus | None,
        category: ApprovalCategory | None = None,
        limit: int,
        offset: int,
        cursor: str | None = None,
    ) -> list[ApprovalListItem]:
        return self.list_approval_page(
            user=user,
            status=status,
            category=category,
            limit=limit,
            offset=offset,
            cursor=cursor,
        ).items

    def list_approval_page(
        self,
        *,
        user: User,
        status: ApprovalRequestStatus | None,
        category: ApprovalCategory | None = None,
        limit: int,
        offset: int,
        cursor: str | None = None,
    ) -> ApprovalListPage:
        actor = approval_actor_for_user(user)
        _ensure_action(actor, "list")
        normalized_limit = min(max(1, limit), APPROVAL_LIST_MAX_LIMIT)
        normalized_offset = max(0, offset)
        statuses = (status,) if status is not None else None
        try:
            decoded_cursor = decode_approval_request_cursor(cursor)
        except ValueError as exc:
            raise ApprovalInvalidRequestError(str(exc)) from None
        visibility = _approval_list_visibility(
            self.db,
            user=user,
            actor=actor,
            category=category,
        )
        if visibility.empty:
            return ApprovalListPage(items=[], next_cursor=None)

        records = self.approval_repo.query_records(
            statuses=statuses,
            categories=visibility.categories,
            module_tokens=tuple(visibility.module_tokens or ()),
            limit=normalized_limit,
            offset=normalized_offset,
            cursor=decoded_cursor,
        )
        visible_records = [
            record
            for record in records
            if _record_matches_visibility(record, visibility)
        ]
        items: list[ApprovalListItem] = []
        workflows = self.workflow_repo.load_by_approval_ids(
            [record.approval_id for record in visible_records]
        )
        for record in visible_records:
            workflow = workflows.get(record.approval_id)
            items.append(_list_item(record, workflow))
        next_cursor = (
            encode_approval_request_cursor(visible_records[-1])
            if len(visible_records) == normalized_limit
            else None
        )
        return ApprovalListPage(items=items, next_cursor=next_cursor)

    def approve(
        self,
        approval_id: str,
        payload: ApprovalDecisionAction,
        *,
        user: User,
        audit: AuditContext | None = None,
    ) -> ApprovalDetailResponse:
        return self._manual_decision(
            approval_id,
            payload=payload,
            user=user,
            status="approved",
            audit=audit,
        )

    def reject(
        self,
        approval_id: str,
        payload: ApprovalDecisionAction,
        *,
        user: User,
        audit: AuditContext | None = None,
    ) -> ApprovalDetailResponse:
        return self._manual_decision(
            approval_id,
            payload=payload,
            user=user,
            status="rejected",
            audit=audit,
        )

    def _manual_decision(
        self,
        approval_id: str,
        *,
        payload: ApprovalDecisionAction,
        user: User,
        status: Literal["approved", "rejected"],
        audit: AuditContext | None,
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
        _ensure_record_visible(self.db, user=user, actor=actor, record=request)
        if _record_category(request) == CONTROL_PLANE_CATEGORY and (
            actor.actor_role != "owner"
        ):
            raise ApprovalPermissionDeniedError("主控审批仅允许 owner 处理。")
        reason = _decision_reason(payload, status=status)
        event_time = _utc_now()
        decision = ApprovalDecision(
            status=status,
            reason=reason,
            decision_source="user",
        )
        workflow = self.workflow_service.apply_manual_decision(
            approval_id,
            decision=decision,
            actor=actor,
            event_time=event_time,
        )
        self._write_decision_audit_log(
            request,
            actor=actor,
            status=status,
            reason=reason,
            event_time=event_time,
            audit=audit,
        )
        self.db.flush()
        execution_unlock = self._sync_unlock_binding(
            workflow.approval_id,
            reveal_token=status == "approved",
        )
        return self._detail_response(
            workflow.approval_id,
            actor=actor,
            user=user,
            workflow=workflow,
            execution_unlock=execution_unlock,
        )

    def _detail_response(
        self,
        approval_id: str,
        *,
        actor: ApprovalActor,
        user: User,
        workflow: ApprovalWorkflow | None = None,
        execution_unlock=None,
    ) -> ApprovalDetailResponse:
        request_record = self.approval_repo.load_record(approval_id)
        if request_record is None:
            raise ApprovalNotFoundError(
                f"Approval '{approval_id}' was not found."
            )
        _ensure_record_visible(self.db, user=user, actor=actor, record=request_record)
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
        if execution_unlock is None:
            execution_unlock = self._describe_unlock_binding(approval_id)
        return ApprovalDetailResponse(
            approval=approval_request_from_record(request_record),
            workflow=workflow,
            decisions=[_decision_response(record) for record in decisions],
            display=approval_display_info(
                module_key=request_record.module_key,
                action_key=request_record.action_key,
                category=_record_category(request_record),
                status=request_record.status,
                risk_level=request_record.risk_level,
            ),
            permission_boundary=actor.permission_boundary(),
            execution_unlock=execution_unlock,
            safety=ApprovalSafetyBoundaryResponse(),
        )

    def _write_decision_audit_log(
        self,
        request_record: ApprovalRequestRecord,
        *,
        actor: ApprovalActor,
        status: Literal["approved", "rejected"],
        reason: str,
        event_time: datetime,
        audit: AuditContext | None,
    ) -> None:
        category = _record_category(request_record)
        event_type = f"approval.{status}"
        context_id = (
            audit.request_id
            if audit is not None and audit.request_id
            else request_record.approval_id
        )
        payload = {
            "action": event_type,
            "approval_action": "approve" if status == "approved" else "reject",
            "approval_id": request_record.approval_id,
            "organization_id": request_record.org_id,
            "user_id": actor.user_id,
            "module": request_record.module_key,
            "module_key": request_record.module_key,
            "category": category,
            "reason": reason if status == "rejected" else "",
            "decision_reason": reason,
            "decision_status": status,
            "timestamp": event_time.isoformat(),
            "metadata": {
                "audit_family": "system_approval",
                "approval_category": category,
                "actor_role": actor.actor_role,
            },
        }
        record = StorageRecordEnvelope(
            entity_type="EventRaw",
            tier="L1_hot",
            backend_targets=("postgresql",),
            context_id=context_id,
            trace_id=request_record.execution_id,
            event_id=f"approval-audit-{uuid4()}",
            user_id=str(actor.user_id),
            module="system",
            event_type=event_type,
            timestamp=event_time,
            status=_audit_status(status),
            payload=payload,
        )
        AuditLogWriter(self.db, org_id=request_record.org_id).write_storage_record(
            record,
        )

    def _sync_unlock_binding(
        self,
        approval_id: str,
        *,
        reveal_token: bool,
    ):
        request_record = self.approval_repo.load_record(approval_id)
        if request_record is None:
            return None
        return C12ApprovalUnlockTokenController(self.db).sync_from_approval(
            org_id=request_record.org_id,
            approval_id=approval_id,
            reveal_token=reveal_token,
        )

    def _describe_unlock_binding(self, approval_id: str):
        request_record = self.approval_repo.load_record(approval_id)
        if request_record is None:
            return None
        return C12ApprovalUnlockTokenController(self.db).describe_approval(
            org_id=request_record.org_id,
            approval_id=approval_id,
        )
