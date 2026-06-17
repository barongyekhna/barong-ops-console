from __future__ import annotations

from sqlalchemy import Select

from ..services.data_isolation import current_org_data_isolation_context

ROLLOUT_BACKFILL_ORG_ID = "org_00000000000000000000000000000000"


class TenantIsolationError(PermissionError):
    pass


def current_tenant_org_id() -> str:
    context = current_org_data_isolation_context()
    org_id = None if context is None else context.org_id
    if org_id is None or not org_id.strip():
        raise TenantIsolationError("C18 tenant isolation requires org_id context.")
    return org_id.strip()


def tenant_org_id_for_create() -> str:
    context = current_org_data_isolation_context()
    org_id = None if context is None else context.org_id
    if org_id is None or not org_id.strip():
        return ROLLOUT_BACKFILL_ORG_ID
    return org_id.strip()


def apply_tenant_filter(statement: Select, model: type) -> Select:
    return statement.where(model.org_id == current_tenant_org_id())
