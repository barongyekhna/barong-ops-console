"""Authenticated global identity and directory services for C19."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ...models.user import User
from ...repositories.operation_logs import create_operation_log
from ...services.auth_service import AuditContext
from ...services.data_isolation import without_org_data_isolation
from . import identity_repository
from .identity_repository import C19ProfileBundle
from .identity_sync_service import sync_profile_for_user
from .identity_schemas import (
    C19AffiliationRead,
    C19DirectoryPage,
    C19ProfileRead,
    C19ProfileSummaryRead,
    C19ProfileUpdate,
)


class C19IdentityError(ValueError):
    pass


class C19ActorUnavailableError(PermissionError):
    pass


class C19ProfileNotFoundError(C19IdentityError):
    pass


def require_active_c19_actor(db: Session, *, actor: User) -> None:
    if not actor.is_active:
        raise C19ActorUnavailableError(
            "C19 requires an active account."
        )
    # C19 is a native authenticated-user capability.  Profiles are global and
    # independent of organization membership, so repair a missing projection
    # here without requiring or inventing an affiliation.
    with without_org_data_isolation():
        sync_profile_for_user(db, user=actor)


def profile_summary_from_bundle(
    bundle: C19ProfileBundle,
) -> C19ProfileSummaryRead:
    return C19ProfileSummaryRead(
        user_id=bundle.profile.user_id,
        display_name=bundle.profile.resolved_display_name,
        avatar_ref=bundle.profile.avatar_ref,
        is_bot=bundle.is_bot,
    )


def profile_read_from_bundle(bundle: C19ProfileBundle) -> C19ProfileRead:
    return C19ProfileRead(
        user_id=bundle.profile.user_id,
        display_name=bundle.profile.resolved_display_name,
        avatar_ref=bundle.profile.avatar_ref,
        is_bot=bundle.is_bot,
        bio=bundle.profile.bio,
        affiliations=[
            C19AffiliationRead(
                affiliation_id=item.affiliation.affiliation_id,
                org_id=item.affiliation.org_id,
                org_name=item.organization.org_name,
                org_type=item.organization.org_type,
                role=item.affiliation.role,
                joined_at=item.affiliation.joined_at,
            )
            for item in bundle.affiliations
        ],
    )


def list_directory(
    db: Session,
    *,
    actor: User,
    search: str | None,
    affiliation_org_id: str | None,
    limit: int,
    offset: int,
) -> C19DirectoryPage:
    require_active_c19_actor(db, actor=actor)
    normalized_search = search.strip() if search else None
    normalized_affiliation_org_id = (
        affiliation_org_id.strip() if affiliation_org_id else None
    )
    with without_org_data_isolation():
        bundles, total = identity_repository.list_active_profile_bundles(
            db,
            search=normalized_search or None,
            affiliation_org_id=normalized_affiliation_org_id or None,
            limit=limit,
            offset=offset,
        )
    return C19DirectoryPage(
        items=[profile_read_from_bundle(bundle) for bundle in bundles],
        count=total,
        limit=limit,
        offset=offset,
    )


def get_profile(
    db: Session,
    *,
    actor: User,
    user_id: int,
) -> C19ProfileRead:
    require_active_c19_actor(db, actor=actor)
    with without_org_data_isolation():
        bundle = identity_repository.get_active_profile_bundle(
            db,
            user_id=user_id,
        )
    if bundle is None:
        raise C19ProfileNotFoundError("C19 profile not found.")
    return profile_read_from_bundle(bundle)


def update_own_profile(
    db: Session,
    *,
    actor: User,
    payload: C19ProfileUpdate,
    audit: AuditContext,
) -> C19ProfileRead:
    require_active_c19_actor(db, actor=actor)
    with without_org_data_isolation():
        profile = identity_repository.get_profile_for_update(
            db,
            user_id=actor.id,
        )
        if profile is None:
            raise C19ProfileNotFoundError("C19 profile not found.")

        previous_avatar_ref = profile.avatar_ref
        profile.avatar_ref = payload.avatar_ref
        db.flush()
        bundle = identity_repository.get_active_profile_bundle(
            db,
            user_id=actor.id,
        )
        if bundle is None:
            raise C19ProfileNotFoundError("C19 profile not found.")
        response = profile_read_from_bundle(bundle)

        # Keep the potentially sensitive URL/path out of the audit log.  The
        # durable profile row is authoritative; the log records only lifecycle
        # state and whether this request changed it.
        create_operation_log(
            db,
            actor_type="user",
            actor_id=str(actor.id),
            action="c19.profile.avatar.update",
            target_type="c19_profile",
            target_id=str(actor.id),
            result="success",
            request_id=audit.request_id,
            ip_address=audit.ip_address,
            user_agent=audit.user_agent,
            details={
                "changed": previous_avatar_ref != payload.avatar_ref,
                "cleared": payload.avatar_ref is None,
            },
        )
        db.commit()
    return response


__all__ = [
    "C19ActorUnavailableError",
    "C19IdentityError",
    "C19ProfileNotFoundError",
    "get_profile",
    "list_directory",
    "profile_read_from_bundle",
    "profile_summary_from_bundle",
    "require_active_c19_actor",
    "update_own_profile",
]
