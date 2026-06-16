from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.org_membership import OrgMembershipRecord
from ..schemas.module_binding import ModuleBindRequest, ModuleBinding
from ..schemas.module_visibility import ModuleVisibilityResponse, VisibleModule
from .event_collector import emit_event
from .module_binding_service import list_module_bindings
from .module_registry import list_module_manifests


class ModuleVisibilityError(ValueError):
    pass


class ModuleVisibilityActiveOrgContextRequiredError(ModuleVisibilityError):
    pass


class ModuleVisibilityMembershipRequiredError(PermissionError):
    pass


def _normalize_user_id(user_id: str | int) -> str:
    normalized = str(user_id).strip()
    if not normalized:
        raise ModuleVisibilityError("user_id is required.")
    return normalized


def _normalize_org_id(org_id: str) -> str:
    return ModuleBindRequest(
        module_id="active-org-context",
        org_id=org_id,
        mode="single",
    ).org_id


def _active_memberships_for_user(
    db: Session,
    *,
    user_id: str,
) -> list[OrgMembershipRecord]:
    return list(
        db.scalars(
            select(OrgMembershipRecord)
            .where(
                OrgMembershipRecord.user_id == user_id,
                OrgMembershipRecord.status == "active",
            )
            .order_by(OrgMembershipRecord.org_id)
        )
    )


def _resolve_active_org_id(
    memberships: Sequence[OrgMembershipRecord],
    *,
    active_org_id: str | None,
) -> str:
    active_org_ids = {membership.org_id for membership in memberships}
    if active_org_id is not None:
        scoped_org_id = _normalize_org_id(active_org_id)
        if scoped_org_id not in active_org_ids:
            raise ModuleVisibilityMembershipRequiredError(
                "Active C18C organization membership is required."
            )
        return scoped_org_id

    if not memberships:
        raise ModuleVisibilityMembershipRequiredError(
            "Active C18C organization membership is required."
        )
    if len(memberships) > 1:
        raise ModuleVisibilityActiveOrgContextRequiredError(
            "active_org_id is required for users with multiple active orgs."
        )
    return memberships[0].org_id


def _module_names_by_id() -> dict[str, str]:
    return {
        manifest.module_key: manifest.display_name
        for manifest in list_module_manifests()
    }


def _binding_visible_for_org(binding: ModuleBinding, *, org_id: str) -> bool:
    return binding.enabled and (
        binding.mode == "global" or org_id in binding.bound_orgs
    )


def build_visible_modules_for_org(
    *,
    org_id: str,
    bindings: Sequence[ModuleBinding],
    module_names_by_id: Mapping[str, str] | None = None,
) -> list[VisibleModule]:
    scoped_org_id = _normalize_org_id(org_id)
    names = module_names_by_id or {}
    return [
        VisibleModule(
            module_id=binding.module_id,
            module_name=names.get(binding.module_id, binding.module_id),
            mode=binding.mode,
        )
        for binding in bindings
        if _binding_visible_for_org(binding, org_id=scoped_org_id)
    ]


def get_visible_modules(
    db: Session,
    user_id: str | int,
    active_org_id: str | None = None,
) -> ModuleVisibilityResponse:
    scoped_user_id = _normalize_user_id(user_id)
    memberships = _active_memberships_for_user(db, user_id=scoped_user_id)
    try:
        org_id = _resolve_active_org_id(memberships, active_org_id=active_org_id)
    except (
        ModuleVisibilityActiveOrgContextRequiredError,
        ModuleVisibilityMembershipRequiredError,
    ):
        emit_event(
            event_type="module_visibility.read",
            module="system",
            action="c18e.visible_modules",
            source="backend",
            status="failed",
            user_id=scoped_user_id,
            payload={
                "stage": "C18E",
                "requested_org_id": active_org_id,
                "active_membership_count": len(memberships),
                "module_visibility_only": True,
                "data_access_granted": False,
            },
        )
        raise

    bindings = list_module_bindings()
    visible_modules = build_visible_modules_for_org(
        org_id=org_id,
        bindings=bindings,
        module_names_by_id=_module_names_by_id(),
    )
    emit_event(
        event_type="module_visibility.read",
        module="system",
        action="c18e.visible_modules",
        source="backend",
        status="success",
        user_id=scoped_user_id,
        payload={
            "stage": "C18E",
            "org_id": org_id,
            "active_membership_count": len(memberships),
            "visible_module_count": len(visible_modules),
            "module_visibility_only": True,
            "data_access_granted": False,
        },
    )
    return ModuleVisibilityResponse(
        user_id=scoped_user_id,
        org_id=org_id,
        visible_modules=visible_modules,
    )
