from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.roles import is_owner_role
from ..models.organization import OrganizationRecord
from ..models.user import User
from ..repositories.operation_logs import create_operation_log
from ..repositories.org_memberships import create_org_membership_record
from ..repositories.organizations import (
    create_organization_record,
    get_organization,
    update_organization_record,
)
from ..schemas.organization import (
    Organization,
    OrganizationCreate,
    OrganizationLifecycleOperation,
    OrganizationLifecyclePermissionError,
    OrganizationLifecycleUpdate,
    OrganizationMetadata,
    OrganizationStatus,
    OrganizationStatusTransitionError,
    enforce_organization_status_transition,
    enforce_owner_can_create_organization,
    enforce_owner_only_org_lifecycle,
    generate_org_id,
)
from ..schemas.org_membership import generate_membership_id
from .auth_service import AuditContext
from .permission_resolution_cache import clear_permission_ttl_cache


class OrganizationLifecycleError(ValueError):
    pass


class OrganizationNotFoundError(OrganizationLifecycleError):
    pass


class OrganizationDuplicateError(OrganizationLifecycleError):
    pass


class OrganizationOwnerDeniedError(PermissionError):
    pass


class OrganizationStatusConflictError(OrganizationLifecycleError):
    pass


def _actor_user_id(actor: User) -> str:
    return str(actor.id)


def _metadata_dict(metadata: OrganizationMetadata) -> dict[str, Any]:
    return metadata.model_dump(mode="json")


def _record_to_schema(record: OrganizationRecord) -> Organization:
    return Organization(
        org_id=record.org_id,
        org_name=record.org_name,
        org_type=record.org_type,
        owner_user_id=record.owner_user_id,
        status=record.status,
        metadata=OrganizationMetadata.model_validate(record.metadata_json or {}),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _log_org_operation(
    db: Session,
    *,
    actor: User,
    action: str,
    target_id: str,
    result: str,
    audit: AuditContext,
    error_code: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    create_operation_log(
        db,
        actor_type="user",
        actor_id=_actor_user_id(actor),
        action=action,
        target_type="organization",
        target_id=target_id,
        result=result,
        error_code=error_code,
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details=details,
    )


def _log_and_commit_failure(
    db: Session,
    *,
    actor: User,
    action: str,
    target_id: str,
    audit: AuditContext,
    error_code: str,
    details: dict[str, object] | None = None,
) -> None:
    _log_org_operation(
        db,
        actor=actor,
        action=action,
        target_id=target_id,
        result="failure",
        error_code=error_code,
        audit=audit,
        details=details,
    )
    db.commit()


def _get_required_organization(
    db: Session,
    *,
    org_id: str,
    actor: User,
    action: str,
    audit: AuditContext,
) -> OrganizationRecord:
    organization = get_organization(db, org_id)
    if organization is None:
        _log_and_commit_failure(
            db,
            actor=actor,
            action=action,
            target_id=org_id,
            audit=audit,
            error_code="org_not_found",
        )
        raise OrganizationNotFoundError("Organization not found.")
    return organization


def _enforce_owner_for_record(
    db: Session,
    *,
    organization: OrganizationRecord,
    actor: User,
    action: str,
    operation: OrganizationLifecycleOperation,
    audit: AuditContext,
) -> None:
    try:
        enforce_owner_only_org_lifecycle(
            actor_user_id=_actor_user_id(actor),
            owner_user_id=organization.owner_user_id,
            operation=operation,
        )
    except OrganizationLifecyclePermissionError as exc:
        _log_and_commit_failure(
            db,
            actor=actor,
            action=action,
            target_id=organization.org_id,
            audit=audit,
            error_code="owner_only_denied",
            details={"operation": operation.value},
        )
        raise OrganizationOwnerDeniedError(str(exc)) from None


def _enforce_transition_for_record(
    db: Session,
    *,
    organization: OrganizationRecord,
    actor: User,
    action: str,
    operation: OrganizationLifecycleOperation,
    to_status: OrganizationStatus,
    audit: AuditContext,
) -> None:
    try:
        enforce_organization_status_transition(
            from_status=organization.status,
            to_status=to_status,
            operation=operation,
        )
    except OrganizationStatusTransitionError as exc:
        _log_and_commit_failure(
            db,
            actor=actor,
            action=action,
            target_id=organization.org_id,
            audit=audit,
            error_code="invalid_status_transition",
            details={
                "operation": operation.value,
                "from_status": organization.status,
                "to_status": to_status.value,
            },
        )
        raise OrganizationStatusConflictError(str(exc)) from None


def create_organization(
    db: Session,
    *,
    payload: OrganizationCreate,
    actor: User,
    audit: AuditContext,
) -> Organization:
    action = "org.create"
    if not is_owner_role(actor.role):
        _log_and_commit_failure(
            db,
            actor=actor,
            action=action,
            target_id="pending_org",
            audit=audit,
            error_code="owner_role_required",
            details={"actor_role": actor.role},
        )
        raise OrganizationOwnerDeniedError("Owner role required.")
    try:
        enforce_owner_can_create_organization(
            actor_user_id=_actor_user_id(actor),
            payload=payload,
        )
    except OrganizationLifecyclePermissionError as exc:
        _log_and_commit_failure(
            db,
            actor=actor,
            action=action,
            target_id="pending_org",
            audit=audit,
            error_code="owner_only_denied",
            details={"payload_owner_user_id": payload.owner_user_id},
        )
        raise OrganizationOwnerDeniedError(str(exc)) from None

    try:
        organization = create_organization_record(
            db,
            org_id=generate_org_id(),
            org_name=payload.org_name,
            org_type=payload.org_type.value,
            owner_user_id=payload.owner_user_id,
            metadata=_metadata_dict(payload.metadata),
        )
        create_org_membership_record(
            db,
            membership_id=generate_membership_id(),
            user_id=organization.owner_user_id,
            org_id=organization.org_id,
            role="owner",
            status="active",
            joined_at=organization.created_at,
        )
        _log_org_operation(
            db,
            actor=actor,
            action=action,
            target_id=organization.org_id,
            result="success",
            audit=audit,
            details={
                "status": OrganizationStatus.ACTIVE.value,
                "owner_user_id": organization.owner_user_id,
                "org_type": organization.org_type,
            },
        )
        db.commit()
        clear_permission_ttl_cache()
    except IntegrityError:
        db.rollback()
        raise OrganizationDuplicateError("Organization already exists.") from None
    except ValueError:
        db.rollback()
        raise

    db.refresh(organization)
    return _record_to_schema(organization)


def update_organization(
    db: Session,
    *,
    org_id: str,
    payload: OrganizationLifecycleUpdate,
    actor: User,
    audit: AuditContext,
) -> Organization:
    action = "org.update"
    organization = _get_required_organization(
        db,
        org_id=org_id,
        actor=actor,
        action=action,
        audit=audit,
    )
    _enforce_owner_for_record(
        db,
        organization=organization,
        actor=actor,
        action=action,
        operation=OrganizationLifecycleOperation.UPDATE,
        audit=audit,
    )
    _enforce_transition_for_record(
        db,
        organization=organization,
        actor=actor,
        action=action,
        operation=OrganizationLifecycleOperation.UPDATE,
        to_status=OrganizationStatus(organization.status),
        audit=audit,
    )

    before = {
        "org_name": organization.org_name,
        "org_type": organization.org_type,
        "metadata": organization.metadata_json,
        "status": organization.status,
    }
    organization = update_organization_record(
        db,
        organization,
        org_name=payload.org_name,
        org_type=payload.org_type.value if payload.org_type is not None else None,
        metadata=_metadata_dict(payload.metadata)
        if payload.metadata is not None
        else None,
    )
    after = {
        "org_name": organization.org_name,
        "org_type": organization.org_type,
        "metadata": organization.metadata_json,
        "status": organization.status,
    }
    _log_org_operation(
        db,
        actor=actor,
        action=action,
        target_id=organization.org_id,
        result="success",
        audit=audit,
        details={"before": before, "after": after},
    )
    db.commit()
    clear_permission_ttl_cache()
    db.refresh(organization)
    return _record_to_schema(organization)


def delete_organization(
    db: Session,
    *,
    org_id: str,
    actor: User,
    audit: AuditContext,
) -> Organization:
    return _transition_organization_status(
        db,
        org_id=org_id,
        actor=actor,
        audit=audit,
        operation=OrganizationLifecycleOperation.DELETE,
        to_status=OrganizationStatus.DELETED,
        action="org.delete",
    )


def activate_organization(
    db: Session,
    *,
    org_id: str,
    actor: User,
    audit: AuditContext,
) -> Organization:
    return _transition_organization_status(
        db,
        org_id=org_id,
        actor=actor,
        audit=audit,
        operation=OrganizationLifecycleOperation.ACTIVATE,
        to_status=OrganizationStatus.ACTIVE,
        action="org.activate",
    )


def suspend_organization(
    db: Session,
    *,
    org_id: str,
    actor: User,
    audit: AuditContext,
) -> Organization:
    return _transition_organization_status(
        db,
        org_id=org_id,
        actor=actor,
        audit=audit,
        operation=OrganizationLifecycleOperation.SUSPEND,
        to_status=OrganizationStatus.SUSPENDED,
        action="org.suspend",
    )


def _transition_organization_status(
    db: Session,
    *,
    org_id: str,
    actor: User,
    audit: AuditContext,
    operation: OrganizationLifecycleOperation,
    to_status: OrganizationStatus,
    action: str,
) -> Organization:
    organization = _get_required_organization(
        db,
        org_id=org_id,
        actor=actor,
        action=action,
        audit=audit,
    )
    _enforce_owner_for_record(
        db,
        organization=organization,
        actor=actor,
        action=action,
        operation=operation,
        audit=audit,
    )
    _enforce_transition_for_record(
        db,
        organization=organization,
        actor=actor,
        action=action,
        operation=operation,
        to_status=to_status,
        audit=audit,
    )

    before_status = organization.status
    organization = update_organization_record(
        db,
        organization,
        status=to_status.value,
    )
    _log_org_operation(
        db,
        actor=actor,
        action=action,
        target_id=organization.org_id,
        result="success",
        audit=audit,
        details={
            "before": {"status": before_status},
            "after": {"status": organization.status},
            "soft_delete": operation == OrganizationLifecycleOperation.DELETE,
        },
    )
    db.commit()
    clear_permission_ttl_cache()
    db.refresh(organization)
    return _record_to_schema(organization)
