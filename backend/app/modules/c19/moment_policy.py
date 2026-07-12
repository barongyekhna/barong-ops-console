"""Fail-closed audience construction and current-access context for Moments."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ...models.user import User
from ...services.data_isolation import without_org_data_isolation
from . import moment_repository
from .moment_storage import MomentViewerContextDTO, MomentVisibility


class C19MomentPolicyError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class MomentAudienceResolution:
    audience_user_ids: tuple[str, ...]
    audience_org_ids: tuple[str, ...]
    author_org_id: str | None


def _access_denied() -> C19MomentPolicyError:
    return C19MomentPolicyError(
        code="c19_access_denied",
        message="C19 access denied.",
        status_code=403,
    )


def actor_user_id(actor: User) -> int:
    if not actor.is_active:
        raise _access_denied()
    try:
        value = int(actor.id)
    except (TypeError, ValueError):
        raise _access_denied() from None
    if value <= 0:
        raise _access_denied()
    return value


def build_viewer_context(
    db: Session,
    *,
    actor: User,
) -> MomentViewerContextDTO:
    user_id = actor_user_id(actor)
    with without_org_data_isolation():
        active_user_ids = moment_repository.list_active_user_ids(db)
        if user_id not in active_user_ids:
            raise _access_denied()
        active_org_ids = moment_repository.list_active_org_ids(
            db,
            user_id=user_id,
        )
        friend_user_ids = moment_repository.list_friend_user_ids(
            db,
            user_id=user_id,
        )
        blocked_user_ids = moment_repository.list_blocked_user_ids(
            db,
            user_id=user_id,
        )

    # Passing only live participants makes current Barong identity state a
    # tightening boundary; stale friendship rows can never broaden access.
    live_friends = (friend_user_ids & active_user_ids) - blocked_user_ids
    return MomentViewerContextDTO(
        viewer_user_id=str(user_id),
        active_user_ids=tuple(str(value) for value in sorted(active_user_ids)),
        active_org_ids=tuple(sorted(active_org_ids)),
        friend_user_ids=tuple(str(value) for value in sorted(live_friends)),
        blocked_user_ids=tuple(
            str(value) for value in sorted(blocked_user_ids)
        ),
    )


def resolve_publish_audience(
    db: Session,
    *,
    actor: User,
    visibility: MomentVisibility,
    audience_affiliation_ids: list[str],
) -> MomentAudienceResolution:
    user_id = actor_user_id(actor)
    requested_affiliations = set(audience_affiliation_ids)
    if len(requested_affiliations) != len(audience_affiliation_ids):
        raise C19MomentPolicyError(
            code="c19_moment_audience_invalid",
            message="Moment audience is invalid.",
            status_code=422,
        )

    with without_org_data_isolation():
        active_user_ids = moment_repository.list_active_user_ids(db)
        if user_id not in active_user_ids:
            raise _access_denied()
        blocked_user_ids = moment_repository.list_blocked_user_ids(
            db,
            user_id=user_id,
        )
        organization_ids: set[str] = set()
        if visibility == "org":
            resolved = moment_repository.resolve_owned_affiliations(
                db,
                user_id=user_id,
                affiliation_ids=requested_affiliations,
            )
            if not requested_affiliations or set(resolved) != requested_affiliations:
                raise C19MomentPolicyError(
                    code="c19_moment_audience_invalid",
                    message="Moment audience is invalid.",
                    status_code=422,
                )
            organization_ids = set(resolved.values())
            audience_user_ids = moment_repository.list_active_user_ids_for_orgs(
                db,
                org_ids=organization_ids,
            )
        elif requested_affiliations:
            raise C19MomentPolicyError(
                code="c19_moment_audience_invalid",
                message="Moment audience is invalid.",
                status_code=422,
            )
        elif visibility == "public":
            audience_user_ids = set(active_user_ids)
        elif visibility == "friends":
            audience_user_ids = moment_repository.list_friend_user_ids(
                db,
                user_id=user_id,
            ) & active_user_ids
        elif visibility == "private":
            audience_user_ids = {user_id}
        else:
            raise C19MomentPolicyError(
                code="c19_moment_audience_invalid",
                message="Moment audience is invalid.",
                status_code=422,
            )

    audience_user_ids -= blocked_user_ids
    audience_user_ids.add(user_id)
    ordered_org_ids = tuple(sorted(organization_ids))
    return MomentAudienceResolution(
        audience_user_ids=tuple(
            str(value) for value in sorted(audience_user_ids)
        ),
        audience_org_ids=ordered_org_ids,
        # This is descriptive only, never the authority for organization
        # visibility.  A multi-affiliation global card has no guessed primary.
        author_org_id=ordered_org_ids[0] if len(ordered_org_ids) == 1 else None,
    )


__all__ = [
    "C19MomentPolicyError",
    "MomentAudienceResolution",
    "actor_user_id",
    "build_viewer_context",
    "resolve_publish_audience",
]
