"""Shared cross-org guard for single-target-organization modules.

F / W / H / B2B business tables have neither an `org_id` column nor a
`workspace_key`, so the global org-data-isolation layer cannot scope them and
row-level filtering is impossible. Each of these modules serves exactly one
target organization (`TARGET_ORGANIZATION_NAME`). The only place isolation can
be enforced is the authorization gate: the caller's org must equal the target
org, otherwise a super_admin of another org (e.g. the factory org) can read the
international-trade org's prospects, orders, sourcing candidates, etc.

This mirrors the CS module's `_require_cs_permission` gate (the one module that
already did this correctly) and collapses it into a single reusable dependency
so F/W/H/B2B don't each re-implement it.

QA sweep 2026-08-22, finding H1.
"""
from __future__ import annotations

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.roles import is_owner_role
from ..models.organization import OrganizationRecord
from ..models.user import User
from ..services.data_isolation import without_org_data_isolation

# Canonical name of the single organization that F / W / H / B2B serve. Several
# modules already define this same literal locally; this shared constant is the
# one to use for modules that lack their own (e.g. H site-health).
INTERNATIONAL_TRADE_ORG_NAME = "涌龙麟（深圳）国际贸易有限公司"


def resolve_caller_org(request: Request, user: User) -> str:
    """The caller's organization id, from the server-set request context first
    (never a client payload) and falling back to the user's own org."""
    candidate = getattr(request.state, "org_id", None)
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    fallback = getattr(user, "organization_id", None)
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()
    return ""


def resolve_target_org(db: Session, target_name: str) -> OrganizationRecord | None:
    """The single organization this module belongs to, looked up by name.

    Read under `without_org_data_isolation()` because the organizations table is
    org-scoped and the caller may legitimately not match while we resolve it.
    Returns None if the name is missing or ambiguous (fail closed at the gate).
    """
    with without_org_data_isolation():
        organizations = list(
            db.scalars(
                select(OrganizationRecord)
                .where(
                    OrganizationRecord.org_name == target_name,
                    OrganizationRecord.status == "active",
                )
                .order_by(OrganizationRecord.org_id)
                .limit(2)
            )
        )
    if len(organizations) != 1:
        return None
    return organizations[0]


def enforce_caller_is_target_org(
    request: Request,
    db: Session,
    user: User,
    *,
    target_name: str,
    detail: str = "You do not have access to this workspace.",
) -> str:
    """Raise 403 unless the caller's org is this module's single target org.

    Returns the caller org id on success so callers can reuse it. This is the
    cross-org isolation for modules whose tables cannot be row-filtered.

    The platform owner is global (the proprietor, owner of every org) and is
    never org-restricted; only super_admins and below are pinned to their org.
    """
    if is_owner_role(user.role):
        return resolve_caller_org(request, user)

    caller_org = resolve_caller_org(request, user)
    target = resolve_target_org(db, target_name)
    if target is None or not caller_org or target.org_id != caller_org:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )
    return caller_org
