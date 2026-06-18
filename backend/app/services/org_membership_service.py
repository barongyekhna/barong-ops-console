from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.org_membership import OrgMembershipRecord
from ..models.organization import OrganizationRecord
from ..models.user import User
from ..repositories.operation_logs import create_operation_log
from ..repositories.org_memberships import (
    create_org_membership_record,
    get_membership_by_user_org,
    get_owner_membership_by_org,
    list_memberships_by_org,
    update_org_membership_record,
)
from ..repositories.organizations import get_organization
from ..repositories.users import get_user_by_id
from ..schemas.org_membership import (
    OrgMemberAddRequest,
    OrgMemberRemoveRequest,
    OrgMembership,
    OrgMembershipOperation,
    OrgMembershipPermissionError,
    OrgMembershipRole,
    OrgMembershipStatus,
    enforce_org_membership_permission,
    generate_membership_id,
)
from .auth_service import AuditContext
from .permission_resolution_cache import clear_permission_ttl_cache


class OrgMembershipError(ValueError):
    pass


class OrgMembershipOrganizationNotFoundError(OrgMembershipError):
    pass


class OrgMembershipUserNotFoundError(OrgMembershipError):
    pass


class OrgMembershipPermissionDeniedError(PermissionError):
    pass


class OrgMembershipConflictError(OrgMembershipError):
    pass


class OrgOwnerMembershipImmutableError(OrgMembershipConflictError):
    pass


class OrgMembershipNotFoundError(OrgMembershipError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _actor_user_id(actor: User) -> str:
    return str(actor.id)


def _record_to_schema(record: OrgMembershipRecord) -> OrgMembership:
    return OrgMembership(
        membership_id=record.membership_id,
        user_id=record.user_id,
        org_id=record.org_id,
        role=record.role,
        status=record.status,
        joined_at=record.joined_at,
    )


def _log_membership_operation(
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
        target_type="org_membership",
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
    _log_membership_operation(
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
        raise OrgMembershipOrganizationNotFoundError("Organization not found.")
    return organization


def _get_required_user(
    db: Session,
    *,
    user_id: str,
) -> User:
    try:
        user_pk = int(user_id)
    except ValueError:
        raise OrgMembershipUserNotFoundError("User not found.") from None
    user = get_user_by_id(db, user_pk)
    if user is None:
        raise OrgMembershipUserNotFoundError("User not found.")
    return user


def _ensure_owner_membership(
    db: Session,
    *,
    organization: OrganizationRecord,
) -> OrgMembershipRecord:
    owner_user_id = organization.owner_user_id.strip()
    owner_membership = get_owner_membership_by_org(db, org_id=organization.org_id)
    if owner_membership is not None and owner_membership.user_id != owner_user_id:
        raise OrgMembershipConflictError(
            "Organization already has a different owner membership."
        )

    membership = get_membership_by_user_org(
        db,
        user_id=owner_user_id,
        org_id=organization.org_id,
    )
    if membership is None:
        return create_org_membership_record(
            db,
            membership_id=generate_membership_id(),
            user_id=owner_user_id,
            org_id=organization.org_id,
            role=OrgMembershipRole.OWNER.value,
            status=OrgMembershipStatus.ACTIVE.value,
            joined_at=organization.created_at or _now(),
        )

    if (
        membership.role != OrgMembershipRole.OWNER.value
        or membership.status != OrgMembershipStatus.ACTIVE.value
    ):
        return update_org_membership_record(
            db,
            membership,
            role=OrgMembershipRole.OWNER.value,
            status=OrgMembershipStatus.ACTIVE.value,
        )

    return membership


def _enforce_actor_membership_operation(
    db: Session,
    *,
    organization: OrganizationRecord,
    actor: User,
    operation: OrgMembershipOperation,
    action: str,
    audit: AuditContext,
) -> OrgMembershipRecord:
    membership = get_membership_by_user_org(
        db,
        user_id=_actor_user_id(actor),
        org_id=organization.org_id,
    )
    try:
        enforce_org_membership_permission(
            actor_user_id=_actor_user_id(actor),
            org_id=organization.org_id,
            operation=operation,
            role=membership.role if membership is not None else None,
            status=membership.status if membership is not None else None,
        )
    except OrgMembershipPermissionError as exc:
        _log_and_commit_failure(
            db,
            actor=actor,
            action=action,
            target_id=organization.org_id,
            audit=audit,
            error_code="membership_permission_denied",
            details={
                "operation": operation.value,
                "actor_membership_role": membership.role
                if membership is not None
                else None,
                "actor_membership_status": membership.status
                if membership is not None
                else None,
            },
        )
        raise OrgMembershipPermissionDeniedError(str(exc)) from None

    if membership is None:
        raise OrgMembershipPermissionDeniedError("User is not in organization.")
    return membership


def add_org_member(
    db: Session,
    *,
    org_id: str,
    payload: OrgMemberAddRequest,
    actor: User,
    audit: AuditContext,
) -> OrgMembership:
    action = "org.members.add"
    organization = _get_required_organization(
        db,
        org_id=org_id,
        actor=actor,
        action=action,
        audit=audit,
    )
    try:
        _ensure_owner_membership(db, organization=organization)
    except OrgMembershipConflictError:
        _log_and_commit_failure(
            db,
            actor=actor,
            action=action,
            target_id=org_id,
            audit=audit,
            error_code="owner_membership_conflict",
        )
        raise

    _enforce_actor_membership_operation(
        db,
        organization=organization,
        actor=actor,
        operation=OrgMembershipOperation.ADD_MEMBER,
        action=action,
        audit=audit,
    )

    try:
        target_user = _get_required_user(db, user_id=payload.user_id)
    except OrgMembershipUserNotFoundError:
        _log_and_commit_failure(
            db,
            actor=actor,
            action=action,
            target_id=org_id,
            audit=audit,
            error_code="user_not_found",
            details={"target_user_id": payload.user_id},
        )
        raise

    target_user_id = str(target_user.id)
    requested_role = payload.role
    if target_user_id == organization.owner_user_id:
        requested_role = OrgMembershipRole.OWNER
    elif requested_role == OrgMembershipRole.OWNER:
        _log_and_commit_failure(
            db,
            actor=actor,
            action=action,
            target_id=org_id,
            audit=audit,
            error_code="owner_membership_immutable",
            details={"target_user_id": target_user_id},
        )
        raise OrgOwnerMembershipImmutableError(
            "Owner membership is derived from organization owner_user_id."
        )

    existing = get_membership_by_user_org(
        db,
        user_id=target_user_id,
        org_id=organization.org_id,
    )
    before = None
    try:
        if existing is None:
            membership = create_org_membership_record(
                db,
                membership_id=generate_membership_id(),
                user_id=target_user_id,
                org_id=organization.org_id,
                role=requested_role.value,
                status=OrgMembershipStatus.ACTIVE.value,
                joined_at=_now(),
            )
        else:
            before = {
                "role": existing.role,
                "status": existing.status,
                "joined_at": existing.joined_at.isoformat()
                if existing.joined_at is not None
                else None,
            }
            joined_at = (
                _now()
                if existing.status != OrgMembershipStatus.ACTIVE.value
                else None
            )
            membership = update_org_membership_record(
                db,
                existing,
                role=requested_role.value,
                status=OrgMembershipStatus.ACTIVE.value,
                joined_at=joined_at,
            )

        _log_membership_operation(
            db,
            actor=actor,
            action=action,
            target_id=membership.membership_id,
            result="success",
            audit=audit,
            details={
                "org_id": organization.org_id,
                "target_user_id": target_user_id,
                "role": membership.role,
                "status": membership.status,
                "before": before,
            },
        )
        db.commit()
        clear_permission_ttl_cache()
    except IntegrityError:
        db.rollback()
        raise OrgMembershipConflictError(
            "Organization membership already exists."
        ) from None
    except ValueError:
        db.rollback()
        raise

    db.refresh(membership)
    return _record_to_schema(membership)


def remove_org_member(
    db: Session,
    *,
    org_id: str,
    payload: OrgMemberRemoveRequest,
    actor: User,
    audit: AuditContext,
) -> OrgMembership:
    action = "org.members.remove"
    organization = _get_required_organization(
        db,
        org_id=org_id,
        actor=actor,
        action=action,
        audit=audit,
    )
    try:
        _ensure_owner_membership(db, organization=organization)
    except OrgMembershipConflictError:
        _log_and_commit_failure(
            db,
            actor=actor,
            action=action,
            target_id=org_id,
            audit=audit,
            error_code="owner_membership_conflict",
        )
        raise

    _enforce_actor_membership_operation(
        db,
        organization=organization,
        actor=actor,
        operation=OrgMembershipOperation.REMOVE_MEMBER,
        action=action,
        audit=audit,
    )

    membership = get_membership_by_user_org(
        db,
        user_id=payload.user_id,
        org_id=organization.org_id,
    )
    if membership is None or membership.status != OrgMembershipStatus.ACTIVE.value:
        _log_and_commit_failure(
            db,
            actor=actor,
            action=action,
            target_id=org_id,
            audit=audit,
            error_code="membership_not_found",
            details={"target_user_id": payload.user_id},
        )
        raise OrgMembershipNotFoundError("Organization membership not found.")

    if (
        membership.user_id == organization.owner_user_id
        or membership.role == OrgMembershipRole.OWNER.value
    ):
        _log_and_commit_failure(
            db,
            actor=actor,
            action=action,
            target_id=membership.membership_id,
            audit=audit,
            error_code="owner_membership_immutable",
            details={"target_user_id": membership.user_id},
        )
        raise OrgOwnerMembershipImmutableError(
            "Owner membership cannot be removed through member management."
        )

    before = {"role": membership.role, "status": membership.status}
    try:
        membership = update_org_membership_record(
            db,
            membership,
            status=OrgMembershipStatus.SUSPENDED.value,
        )
        _log_membership_operation(
            db,
            actor=actor,
            action=action,
            target_id=membership.membership_id,
            result="success",
            audit=audit,
            details={
                "org_id": organization.org_id,
                "target_user_id": membership.user_id,
                "before": before,
                "after": {"role": membership.role, "status": membership.status},
            },
        )
        db.commit()
        clear_permission_ttl_cache()
    except ValueError:
        db.rollback()
        raise

    db.refresh(membership)
    return _record_to_schema(membership)


def list_org_members(
    db: Session,
    *,
    org_id: str,
    actor: User,
    audit: AuditContext,
) -> list[OrgMembership]:
    action = "org.members.list"
    organization = _get_required_organization(
        db,
        org_id=org_id,
        actor=actor,
        action=action,
        audit=audit,
    )
    try:
        _ensure_owner_membership(db, organization=organization)
    except OrgMembershipConflictError:
        _log_and_commit_failure(
            db,
            actor=actor,
            action=action,
            target_id=org_id,
            audit=audit,
            error_code="owner_membership_conflict",
        )
        raise

    _enforce_actor_membership_operation(
        db,
        organization=organization,
        actor=actor,
        operation=OrgMembershipOperation.LIST_MEMBERS,
        action=action,
        audit=audit,
    )
    members = list_memberships_by_org(
        db,
        org_id=organization.org_id,
        active_only=True,
    )
    _log_membership_operation(
        db,
        actor=actor,
        action=action,
        target_id=organization.org_id,
        result="success",
        audit=audit,
        details={"org_id": organization.org_id, "count": len(members)},
    )
    db.commit()
    clear_permission_ttl_cache()
    return [_record_to_schema(member) for member in members]
