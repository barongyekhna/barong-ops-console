"""Authoritative policy predicates for effective C19 user blocks."""

from __future__ import annotations

from sqlalchemy import String, cast, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from ...core.roles import (
    ROLE_ALIASES,
    ROLE_OWNER,
    ROLE_SUPER_ADMIN,
)
from ...models.org_membership import OrgMembershipRecord
from ...models.organization import OrganizationRecord
from ...models.user import User


_SUPER_ADMIN_ROLE_VALUES = tuple(
    sorted(
        {ROLE_SUPER_ADMIN}
        | {
            alias
            for alias, canonical in ROLE_ALIASES.items()
            if canonical == ROLE_SUPER_ADMIN
        }
    )
)


def protected_block_target_condition(
    blocker_user_id_expression,
    blocked_user_id_expression,
):
    """Return a correlated SQL predicate for a currently protected target.

    Owner protection is global. Super-admin protection is scoped to the
    target's authoritative ``User.organization_id`` and requires the blocker
    to be an active member of that active organization.
    """

    target = aliased(User)
    membership = aliased(OrgMembershipRecord)
    organization = aliased(OrganizationRecord)
    normalized_role = func.lower(func.trim(target.role))

    owner_target = exists(
        select(target.id).where(
            target.id == blocked_user_id_expression,
            normalized_role == ROLE_OWNER,
        )
    )
    scoped_super_admin_target = exists(
        select(target.id)
        .join(
            organization,
            organization.org_id == target.organization_id,
        )
        .join(
            membership,
            membership.org_id == target.organization_id,
        )
        .where(
            target.id == blocked_user_id_expression,
            normalized_role.in_(_SUPER_ADMIN_ROLE_VALUES),
            organization.status == "active",
            membership.user_id == cast(blocker_user_id_expression, String),
            membership.status == "active",
        )
    )
    return or_(owner_target, scoped_super_admin_target)


def effective_block_target_condition(
    blocker_user_id_expression,
    blocked_user_id_expression,
):
    return ~protected_block_target_condition(
        blocker_user_id_expression,
        blocked_user_id_expression,
    )


def is_protected_block_target(
    db: Session,
    *,
    blocker_user_id: int,
    blocked_user_id: int,
) -> bool:
    return bool(
        db.scalar(
            select(
                protected_block_target_condition(
                    blocker_user_id,
                    blocked_user_id,
                )
            )
        )
    )


__all__ = [
    "effective_block_target_condition",
    "is_protected_block_target",
    "protected_block_target_condition",
]
