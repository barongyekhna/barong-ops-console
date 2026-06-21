from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from sqlalchemy import Select, false, func, or_, select
from sqlalchemy.orm import Session

from ..models.approval import ApprovalDecisionRecord, ApprovalRequestRecord
from ..models.organization import OrganizationRecord
from ..models.user import User
from ..schemas.reviews import (
    ReviewAuditAction,
    ReviewAuditEmployee,
    ReviewAuditOrganization,
)
from .approval_productization import (
    approval_category_from_keys,
    approval_module_label,
)
from .data_isolation import without_org_data_isolation

APPROVAL_ACTION_STATUSES = ("approved", "rejected")
DEFAULT_REVIEW_AUDIT_LIMIT = 10
MAX_REVIEW_AUDIT_LIMIT = 10

MODULE_FILTER_TOKENS: dict[str, tuple[str, ...]] = {
    "product": ("product", "products", "p"),
    "products": ("product", "products", "p"),
    "产品": ("product", "products", "p"),
    "artifact": ("artifact", "artifacts", "file"),
    "artifacts": ("artifact", "artifacts", "file"),
    "资料": ("artifact", "artifacts", "file"),
    "review": ("review", "reviews"),
    "reviews": ("review", "reviews"),
    "评审": ("review", "reviews"),
    "permission": ("permission", "permissions", "rbac"),
    "permissions": ("permission", "permissions", "rbac"),
    "权限": ("permission", "permissions", "rbac"),
    "user": ("user", "users", "account"),
    "users": ("user", "users", "account"),
    "用户": ("user", "users", "account"),
    "module": ("module", "modules"),
    "modules": ("module", "modules"),
    "模块": ("module", "modules"),
    "business": ("business",),
    "业务": ("business",),
}


@dataclass(frozen=True)
class ReviewAuditScope:
    role: str
    current_org_id: str | None
    is_owner: bool


@dataclass(frozen=True)
class ReviewAuditFilters:
    organization_id: str | None = None
    employee: str | None = None
    employee_id: int | None = None
    module: str | None = None
    start_date: date | None = None
    end_date: date | None = None


def _escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _date_start(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _date_end(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _module_tokens(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    normalized = value.strip().lower()
    if not normalized:
        return ()
    return MODULE_FILTER_TOKENS.get(normalized, (normalized,))


def _apply_common_filters(
    statement: Select,
    *,
    scope: ReviewAuditScope,
    filters: ReviewAuditFilters,
    organization_id: str | None = None,
    user_id: int | None = None,
) -> Select:
    effective_org_id = organization_id or filters.organization_id
    if not scope.is_owner:
        effective_org_id = scope.current_org_id

    statement = statement.where(
        ApprovalDecisionRecord.status.in_(APPROVAL_ACTION_STATUSES),
        ApprovalDecisionRecord.actor_id.is_not(None),
    )
    if not scope.is_owner and not effective_org_id:
        return statement.where(false())
    if effective_org_id:
        statement = statement.where(ApprovalDecisionRecord.org_id == effective_org_id)
    effective_user_id = user_id if user_id is not None else filters.employee_id
    if effective_user_id is not None:
        statement = statement.where(ApprovalDecisionRecord.actor_id == effective_user_id)

    employee = filters.employee.strip() if filters.employee else ""
    if employee:
        escaped = _escape_like(employee.lower())
        statement = statement.where(
            or_(
                func.lower(User.username).like(f"%{escaped}%", escape="\\"),
                func.lower(User.job_title).like(f"%{escaped}%", escape="\\"),
            )
        )

    module_tokens = _module_tokens(filters.module)
    if module_tokens:
        module_key = func.lower(ApprovalRequestRecord.module_key)
        action_key = func.lower(ApprovalRequestRecord.action_key)
        module_filters = []
        for token in module_tokens:
            escaped = _escape_like(token)
            module_filters.extend(
                (
                    module_key == token,
                    action_key == token,
                    module_key.like(f"%{escaped}%", escape="\\"),
                    action_key.like(f"%{escaped}%", escape="\\"),
                )
            )
        statement = statement.where(or_(*module_filters))

    start_at = _date_start(filters.start_date)
    end_at = _date_end(filters.end_date)
    if start_at is not None:
        statement = statement.where(ApprovalDecisionRecord.decision_time >= start_at)
    if end_at is not None:
        statement = statement.where(ApprovalDecisionRecord.decision_time <= end_at)

    return statement


def _query_context(scope: ReviewAuditScope):
    del scope
    return without_org_data_isolation()


def list_review_audit_organizations(
    db: Session,
    *,
    scope: ReviewAuditScope,
    filters: ReviewAuditFilters,
    limit: int,
    offset: int,
) -> list[ReviewAuditOrganization]:
    metrics_statement = (
        select(
            ApprovalDecisionRecord.org_id.label("org_id"),
            func.count(ApprovalDecisionRecord.id).label("action_count"),
            func.count(func.distinct(ApprovalDecisionRecord.actor_id)).label(
                "employee_count"
            ),
            func.max(ApprovalDecisionRecord.decision_time).label("latest_action_at"),
        )
        .select_from(ApprovalDecisionRecord)
        .outerjoin(
            ApprovalRequestRecord,
            ApprovalDecisionRecord.approval_id == ApprovalRequestRecord.approval_id,
        )
        .outerjoin(User, ApprovalDecisionRecord.actor_id == User.id)
    )
    metrics_statement = _apply_common_filters(
        metrics_statement,
        scope=scope,
        filters=filters,
    ).group_by(ApprovalDecisionRecord.org_id)
    metrics = metrics_statement.subquery()

    effective_org_id = filters.organization_id if scope.is_owner else scope.current_org_id
    statement = (
        select(
            OrganizationRecord.org_id,
            OrganizationRecord.org_name,
            OrganizationRecord.org_type,
            metrics.c.action_count,
            metrics.c.employee_count,
            metrics.c.latest_action_at,
        )
        .select_from(OrganizationRecord)
        .outerjoin(metrics, metrics.c.org_id == OrganizationRecord.org_id)
        .where(OrganizationRecord.status != "deleted")
    )
    if not scope.is_owner and not effective_org_id:
        statement = statement.where(false())
    if effective_org_id:
        statement = statement.where(OrganizationRecord.org_id == effective_org_id)
    statement = statement.order_by(
        metrics.c.latest_action_at.desc().nulls_last(),
        OrganizationRecord.org_name.asc(),
        OrganizationRecord.org_id.asc(),
    ).offset(offset).limit(limit)

    with _query_context(scope):
        rows = db.execute(statement).all()

    return [
        ReviewAuditOrganization(
            organization_id=row.org_id,
            organization_name=row.org_name or row.org_id,
            organization_type=row.org_type or "组织",
            employee_count=int(row.employee_count or 0),
            action_count=int(row.action_count or 0),
            latest_action_at=row.latest_action_at,
        )
        for row in rows
        if row.org_id
    ]


def list_review_audit_employees(
    db: Session,
    *,
    scope: ReviewAuditScope,
    organization_id: str,
    filters: ReviewAuditFilters,
    limit: int,
    offset: int,
) -> list[ReviewAuditEmployee]:
    statement = (
        select(
            ApprovalDecisionRecord.actor_id,
            User.username,
            User.role,
            User.job_title,
            func.count(ApprovalDecisionRecord.id).label("action_count"),
            func.max(ApprovalDecisionRecord.decision_time).label("latest_action_at"),
        )
        .select_from(ApprovalDecisionRecord)
        .outerjoin(
            ApprovalRequestRecord,
            ApprovalDecisionRecord.approval_id == ApprovalRequestRecord.approval_id,
        )
        .outerjoin(User, ApprovalDecisionRecord.actor_id == User.id)
    )
    statement = _apply_common_filters(
        statement,
        scope=scope,
        filters=filters,
        organization_id=organization_id,
    )
    statement = (
        statement.group_by(
            ApprovalDecisionRecord.actor_id,
            User.username,
            User.role,
            User.job_title,
        )
        .order_by(
            func.max(ApprovalDecisionRecord.decision_time).desc(),
            ApprovalDecisionRecord.actor_id.asc(),
        )
        .offset(offset)
        .limit(limit)
    )

    with _query_context(scope):
        rows = db.execute(statement).all()

    return [
        ReviewAuditEmployee(
            user_id=int(row.actor_id),
            employee_name=row.username or f"员工 {row.actor_id}",
            employee_role=row.role or "员工",
            job_title=row.job_title,
            action_count=int(row.action_count or 0),
            latest_action_at=row.latest_action_at,
        )
        for row in rows
        if row.actor_id is not None
    ]


def _operation_type(status: str) -> str:
    if status == "rejected":
        return "拒绝"
    return "同意"


def _related_object_type(record: ApprovalRequestRecord | None) -> str:
    if record is None:
        return "审批"
    category = approval_category_from_keys(
        module_key=record.module_key,
        action_key=record.action_key,
        adapter_key=record.adapter_key,
        explicit_category=record.category,
    )
    module_label = approval_module_label(record.module_key, category)
    if module_label in {"产品", "资料", "知识"}:
        return module_label
    if record.execution_id:
        return "Job"
    return "Module"


def _related_object(record: ApprovalRequestRecord | None) -> str:
    if record is None:
        return "审批记录"
    object_type = _related_object_type(record)
    if object_type == "Job" and record.execution_id:
        return record.execution_id
    if object_type != "Module":
        return f"{object_type}审批"
    category = approval_category_from_keys(
        module_key=record.module_key,
        action_key=record.action_key,
        adapter_key=record.adapter_key,
        explicit_category=record.category,
    )
    return approval_module_label(record.module_key, category)


def _approval_module(record: ApprovalRequestRecord | None) -> str:
    if record is None:
        return "审批"
    category = approval_category_from_keys(
        module_key=record.module_key,
        action_key=record.action_key,
        adapter_key=record.adapter_key,
        explicit_category=record.category,
    )
    return approval_module_label(record.module_key, category)


def _summary(decision: ApprovalDecisionRecord, request: ApprovalRequestRecord | None) -> str:
    operation = _operation_type(decision.status)
    module = _approval_module(request)
    related_type = _related_object_type(request)
    return f"{module}审批已{operation}，关联对象为{related_type}。"


def list_review_audit_actions(
    db: Session,
    *,
    scope: ReviewAuditScope,
    organization_id: str,
    user_id: int,
    filters: ReviewAuditFilters,
    limit: int,
    offset: int,
) -> list[ReviewAuditAction]:
    statement = (
        select(ApprovalDecisionRecord, ApprovalRequestRecord, User, OrganizationRecord)
        .select_from(ApprovalDecisionRecord)
        .outerjoin(
            ApprovalRequestRecord,
            ApprovalDecisionRecord.approval_id == ApprovalRequestRecord.approval_id,
        )
        .outerjoin(User, ApprovalDecisionRecord.actor_id == User.id)
        .outerjoin(
            OrganizationRecord,
            ApprovalDecisionRecord.org_id == OrganizationRecord.org_id,
        )
    )
    statement = _apply_common_filters(
        statement,
        scope=scope,
        filters=filters,
        organization_id=organization_id,
        user_id=user_id,
    )
    statement = (
        statement.order_by(
            ApprovalDecisionRecord.decision_time.desc(),
            ApprovalDecisionRecord.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )

    with _query_context(scope):
        rows = db.execute(statement).all()

    items: list[ReviewAuditAction] = []
    for decision, request_record, user, organization in rows:
        operation = _operation_type(decision.status)
        items.append(
            ReviewAuditAction(
                audit_id=decision.decision_id,
                organization_id=decision.org_id,
                organization_name=(
                    organization.org_name
                    if organization is not None and organization.org_name
                    else decision.org_id
                ),
                user_id=decision.actor_id or user_id,
                employee_name=(
                    user.username
                    if user is not None and user.username
                    else f"员工 {decision.actor_id or user_id}"
                ),
                approval_module=_approval_module(request_record),
                operation_type=operation,  # type: ignore[arg-type]
                status=decision.status,  # type: ignore[arg-type]
                rejection_reason=decision.reason if decision.status == "rejected" else None,
                action_time=decision.decision_time,
                related_object_type=_related_object_type(request_record),
                related_object=_related_object(request_record),
                summary=_summary(decision, request_record),
            )
        )
    return items

