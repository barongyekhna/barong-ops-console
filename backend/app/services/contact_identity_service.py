from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.roles import is_owner_role
from ..models.contact_identity import ContactIdentityRecord
from ..models.org_membership import OrgMembershipRecord
from ..models.user import User
from ..repositories.contact_identities import (
    create_contact_identity_record,
    get_contact_identity,
    update_contact_identity_record,
)
from ..repositories.operation_logs import create_operation_log
from ..repositories.org_memberships import get_membership_by_user_org
from ..repositories.organizations import get_organization
from ..schemas.contact_identity import (
    CONTACT_IDENTITY_IMMUTABLE_FIELDS,
    ContactIdentity,
    ContactIdentityHireInput,
    ContactIdentityPermissionError,
    ContactIdentityRole,
    ContactIdentityUpdate,
    enforce_contact_identity_update,
)
from .auth_service import AuditContext
from .data_isolation import without_org_data_isolation


class ContactIdentityError(ValueError):
    pass


class ContactIdentityNotFoundError(ContactIdentityError):
    pass


class ContactIdentityOrganizationNotFoundError(ContactIdentityError):
    pass


class ContactIdentityMembershipRequiredError(ContactIdentityError):
    pass


class ContactIdentityConflictError(ContactIdentityError):
    pass


class ContactIdentityPermissionDeniedError(PermissionError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _actor_user_id(actor: User) -> str:
    return str(actor.id)


def _record_to_schema(record: ContactIdentityRecord) -> ContactIdentity:
    return ContactIdentity(
        user_id=record.user_id,
        name=record.name,
        org_id=record.org_id,
        org_name=record.org_name,
        title=record.title,
        role=record.role,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _identity_role_from_membership(
    user: User,
    membership: OrgMembershipRecord,
) -> ContactIdentityRole:
    if is_owner_role(user.role) or membership.role == "owner":
        return ContactIdentityRole.OWNER
    if membership.role == "admin":
        return ContactIdentityRole.ORG_ADMIN
    return ContactIdentityRole.MEMBER


def _active_membership(
    db: Session,
    *,
    user_id: str,
    org_id: str,
) -> OrgMembershipRecord | None:
    membership = get_membership_by_user_org(db, user_id=user_id, org_id=org_id)
    if membership is None or membership.status != "active":
        return None
    return membership


def _actor_identity_scope_for_target(
    db: Session,
    *,
    actor: User,
    target_org_id: str,
) -> tuple[ContactIdentityRole, str | None]:
    if is_owner_role(actor.role):
        return ContactIdentityRole.OWNER, None

    membership = _active_membership(
        db,
        user_id=_actor_user_id(actor),
        org_id=target_org_id,
    )
    if membership is None:
        return ContactIdentityRole.MEMBER, None
    return _identity_role_from_membership(actor, membership), membership.org_id


def _log_identity_operation(
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
        target_type="contact_identity",
        target_id=target_id,
        result=result,
        error_code=error_code,
        request_id=audit.request_id,
        ip_address=audit.ip_address,
        user_agent=audit.user_agent,
        details=details,
    )


def _maybe_log_identity_operation(
    db: Session,
    *,
    actor: User | None,
    action: str,
    target_id: str,
    result: str,
    audit: AuditContext | None,
    error_code: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    if actor is not None and audit is not None:
        _log_identity_operation(
            db,
            actor=actor,
            action=action,
            target_id=target_id,
            result=result,
            audit=audit,
            error_code=error_code,
            details=details,
        )
        return

    create_operation_log(
        db,
        actor_type="user" if actor is not None else "system",
        actor_id=_actor_user_id(actor)
        if actor is not None
        else "contact_identity_service",
        action=action,
        target_type="contact_identity",
        target_id=target_id,
        result=result,
        error_code=error_code,
        request_id=audit.request_id if audit is not None else None,
        ip_address=audit.ip_address if audit is not None else None,
        user_agent=audit.user_agent if audit is not None else None,
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
    _log_identity_operation(
        db,
        actor=actor,
        action=action,
        target_id=target_id,
        result="failure",
        audit=audit,
        error_code=error_code,
        details=details,
    )
    db.commit()


def create_contact_identity(
    db: Session,
    *,
    user: User,
    payload: ContactIdentityHireInput,
    actor: User | None = None,
    audit: AuditContext | None = None,
) -> ContactIdentity:
    action = "contact_identity.create"
    user_id = str(user.id)

    with without_org_data_isolation():
        organization = get_organization(db, payload.org_id)
        if organization is None:
            _maybe_log_identity_operation(
                db,
                actor=actor,
                action=action,
                target_id=user_id,
                result="failure",
                audit=audit,
                error_code="organization_not_found",
                details={"org_id": payload.org_id},
            )
            db.commit()
            raise ContactIdentityOrganizationNotFoundError("Organization not found.")

        membership = _active_membership(db, user_id=user_id, org_id=payload.org_id)
        if membership is None:
            _maybe_log_identity_operation(
                db,
                actor=actor,
                action=action,
                target_id=user_id,
                result="failure",
                audit=audit,
                error_code="active_membership_required",
                details={"org_id": payload.org_id},
            )
            db.commit()
            raise ContactIdentityMembershipRequiredError(
                "Active C18C organization membership is required."
            )

        if get_contact_identity(db, user_id) is not None:
            _maybe_log_identity_operation(
                db,
                actor=actor,
                action=action,
                target_id=user_id,
                result="failure",
                audit=audit,
                error_code="contact_identity_exists",
                details={"org_id": payload.org_id},
            )
            db.commit()
            raise ContactIdentityConflictError("Contact identity already exists.")

        role = _identity_role_from_membership(user, membership)
        try:
            record = create_contact_identity_record(
                db,
                user_id=user_id,
                name=payload.name,
                org_id=payload.org_id,
                org_name=organization.org_name,
                title=payload.title,
                role=role.value,
                created_at=_now(),
                updated_at=_now(),
            )
            _maybe_log_identity_operation(
                db,
                actor=actor,
                action=action,
                target_id=user_id,
                result="success",
                audit=audit,
                details={
                    "org_id": record.org_id,
                    "org_name": record.org_name,
                    "title": record.title,
                    "role": record.role,
                    "locked_fields": list(CONTACT_IDENTITY_IMMUTABLE_FIELDS),
                },
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            raise ContactIdentityConflictError(
                "Contact identity already exists."
            ) from None
        except ValueError:
            db.rollback()
            raise

        db.refresh(record)
    return _record_to_schema(record)


def get_contact_identity_for_actor(
    db: Session,
    *,
    user_id: str,
    actor: User,
    audit: AuditContext,
) -> ContactIdentity:
    action = "contact_identity.read"

    with without_org_data_isolation():
        record = get_contact_identity(db, user_id)
        if record is None:
            raise ContactIdentityNotFoundError("Contact identity not found.")

        if not is_owner_role(actor.role):
            membership = _active_membership(
                db,
                user_id=_actor_user_id(actor),
                org_id=record.org_id,
            )
            if membership is None:
                _log_and_commit_failure(
                    db,
                    actor=actor,
                    action=action,
                    target_id=user_id,
                    audit=audit,
                    error_code="same_org_read_required",
                    details={"target_org_id": record.org_id},
                )
                raise ContactIdentityPermissionDeniedError(
                    "Contact identity read requires same-org membership."
                )

        return _record_to_schema(record)


def update_contact_identity(
    db: Session,
    *,
    user_id: str,
    payload: ContactIdentityUpdate,
    actor: User,
    audit: AuditContext,
) -> ContactIdentity:
    action = "contact_identity.update"
    requested_fields = tuple(
        field_name
        for field_name in CONTACT_IDENTITY_IMMUTABLE_FIELDS
        if field_name in payload.model_fields_set
    )

    with without_org_data_isolation():
        record = get_contact_identity(db, user_id)
        if record is None:
            _log_and_commit_failure(
                db,
                actor=actor,
                action=action,
                target_id=user_id,
                audit=audit,
                error_code="contact_identity_not_found",
            )
            raise ContactIdentityNotFoundError("Contact identity not found.")

        actor_role, actor_org_id = _actor_identity_scope_for_target(
            db,
            actor=actor,
            target_org_id=record.org_id,
        )

        try:
            decision = enforce_contact_identity_update(
                actor_user_id=_actor_user_id(actor),
                target_user_id=record.user_id,
                actor_role=actor_role,
                actor_org_id=actor_org_id,
                target_org_id=record.org_id,
                target_role=record.role,
                requested_fields=requested_fields,
            )
        except ContactIdentityPermissionError as exc:
            _log_and_commit_failure(
                db,
                actor=actor,
                action=action,
                target_id=record.user_id,
                audit=audit,
                error_code="contact_identity_permission_denied",
                details={
                    "actor_role": actor_role.value,
                    "actor_org_id": actor_org_id,
                    "target_org_id": record.org_id,
                    "target_role": record.role,
                    "requested_fields": list(requested_fields),
                },
            )
            raise ContactIdentityPermissionDeniedError(str(exc)) from None

        before = {
            field_name: getattr(record, field_name)
            for field_name in requested_fields
        }
        update_values = {
            field_name: getattr(payload, field_name)
            for field_name in requested_fields
        }

        try:
            record = update_contact_identity_record(db, record, **update_values)
            after = {
                field_name: getattr(record, field_name)
                for field_name in requested_fields
            }
            _log_identity_operation(
                db,
                actor=actor,
                action=action,
                target_id=record.user_id,
                result="success",
                audit=audit,
                details={
                    "decision_reason": decision.reason,
                    "actor_role": actor_role.value,
                    "actor_org_id": actor_org_id,
                    "target_org_id": record.org_id,
                    "requested_fields": list(requested_fields),
                    "before": before,
                    "after": after,
                },
            )
            db.commit()
        except ValueError:
            db.rollback()
            raise

        db.refresh(record)
    return _record_to_schema(record)
