from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from backend.app.schemas.organization import (
    ORGANIZATION_SQL_SCHEMA,
    ORG_CORE_IDENTITY_FIELDS,
    ORG_ID_PATTERN,
    Organization,
    OrganizationCreate,
    OrganizationLifecycleOperation,
    OrganizationLifecyclePermissionError,
    OrganizationMetadata,
    OrganizationMetadataSettings,
    OrganizationType,
    OrganizationUpdate,
    OrgScopedModelMixin,
    enforce_owner_can_create_organization,
    enforce_owner_only_org_lifecycle,
    evaluate_owner_only_org_lifecycle_access,
    generate_org_id,
    get_organization_api_design,
    get_organization_core_schema_completion_status,
    get_organization_data_isolation_design,
    get_organization_security_boundary,
    get_organization_type_constraints,
)


def test_c18a_generate_org_id_uses_immutable_uuid_identifier() -> None:
    org_ids = {generate_org_id() for _ in range(20)}

    assert len(org_ids) == 20
    assert all(ORG_ID_PATTERN.fullmatch(org_id) for org_id in org_ids)
    assert all(not org_id.startswith("store") for org_id in org_ids)


def test_c18a_organization_schema_defines_core_model_and_metadata() -> None:
    organization = Organization(
        org_name="  Barong Store  ",
        org_type=OrganizationType.STORE,
        owner_user_id=" owner-1 ",
        metadata=OrganizationMetadata(
            industry="commerce",
            country="US",
            timezone="America/New_York",
            settings=OrganizationMetadataSettings(
                allow_ai=True,
                allow_n8n=False,
                data_retention_days=90,
            ),
            custom={"tier": "pilot"},
        ),
    )

    assert organization.org_id.startswith("org_")
    assert organization.org_name == "Barong Store"
    assert organization.org_type == OrganizationType.STORE
    assert organization.status == "active"
    assert organization.owner_user_id == "owner-1"
    assert organization.metadata.settings.allow_ai is True
    assert organization.metadata.custom == {"tier": "pilot"}
    assert set(ORG_CORE_IDENTITY_FIELDS) == {
        "org_id",
        "org_name",
        "org_type",
        "owner_user_id",
    }


def test_c18a_org_type_constraints_match_business_domains() -> None:
    constraints = get_organization_type_constraints()
    rules = {rule.org_type: rule for rule in constraints.rules}

    assert set(rules) == {
        OrganizationType.STORE,
        OrganizationType.FACTORY,
        OrganizationType.WAREHOUSE,
    }
    assert "SEO" in rules[OrganizationType.STORE].allowed_scope
    assert "production" in rules[OrganizationType.FACTORY].allowed_scope
    assert "logistics" in rules[OrganizationType.WAREHOUSE].allowed_scope


def test_c18a_create_schema_generates_org_id_internally_only() -> None:
    payload = OrganizationCreate(
        org_name="Factory One",
        org_type="factory",
        owner_user_id="owner-2",
    )

    assert payload.org_type == OrganizationType.FACTORY
    assert "org_id" not in type(payload).model_fields

    with pytest.raises(ValidationError):
        OrganizationCreate(
            org_id="org_should_not_be_accepted",
            org_name="Bad",
            org_type="store",
            owner_user_id="owner-2",
        )


def test_c18a_update_schema_excludes_immutable_org_id() -> None:
    update = OrganizationUpdate(org_name="Warehouse North")

    assert update.org_name == "Warehouse North"
    assert "org_id" not in type(update).model_fields

    with pytest.raises(ValidationError):
        OrganizationUpdate()

    with pytest.raises(ValidationError):
        OrganizationUpdate(org_id="org_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")


def test_c18a_future_models_can_reserve_org_id_without_module_binding() -> None:
    scoped = OrgScopedModelMixin(org_id=generate_org_id())

    assert scoped.org_id.startswith("org_")

    with pytest.raises(ValidationError):
        OrgScopedModelMixin(org_id="store-name-is-not-an-org-id")


def test_c18a_owner_only_lifecycle_enforcement_allows_exact_owner() -> None:
    decision = enforce_owner_only_org_lifecycle(
        actor_user_id="owner-1",
        owner_user_id="owner-1",
        operation=OrganizationLifecycleOperation.RENAME,
    )

    assert decision.allowed is True
    assert decision.denied is False
    assert decision.owner_only_lifecycle_control is True
    assert decision.role_delegation_allowed is False


def test_c18a_owner_only_lifecycle_enforcement_denies_non_owner() -> None:
    decision = evaluate_owner_only_org_lifecycle_access(
        actor_user_id="admin-1",
        owner_user_id="owner-1",
        operation="delete",
    )

    assert decision.allowed is False
    assert decision.denied is True
    assert decision.denial_code == "c18a_owner_only_org_lifecycle_denied"

    with pytest.raises(OrganizationLifecyclePermissionError):
        enforce_owner_only_org_lifecycle(
            actor_user_id="admin-1",
            owner_user_id="owner-1",
            operation="delete",
        )


def test_c18a_create_requires_actor_to_equal_payload_owner() -> None:
    payload = OrganizationCreate(
        org_name="Store One",
        org_type="store",
        owner_user_id="owner-1",
    )

    assert enforce_owner_can_create_organization(
        actor_user_id="owner-1",
        payload=payload,
    ).allowed is True

    with pytest.raises(OrganizationLifecyclePermissionError):
        enforce_owner_can_create_organization(
            actor_user_id="admin-1",
            payload=payload,
        )


def test_c18a_sql_schema_matches_organization_table_contract() -> None:
    compact_sql = re.sub(r"\s+", " ", ORGANIZATION_SQL_SCHEMA)

    assert "CREATE TABLE organizations" in ORGANIZATION_SQL_SCHEMA
    assert "org_id TEXT PRIMARY KEY" in compact_sql
    assert "org_name TEXT NOT NULL" in compact_sql
    assert "org_type TEXT CHECK" in compact_sql
    assert "'store'" in compact_sql
    assert "'factory'" in compact_sql
    assert "'warehouse'" in compact_sql
    assert "owner_user_id TEXT NOT NULL" in compact_sql
    assert "status TEXT DEFAULT 'active'" in compact_sql
    assert "metadata JSONB DEFAULT '{}'::jsonb" in compact_sql
    assert "created_at TIMESTAMP" in compact_sql
    assert "updated_at TIMESTAMP" in compact_sql


def test_c18a_api_design_exposes_required_org_contract_only() -> None:
    design = get_organization_api_design()
    routes = {(endpoint.method, endpoint.path) for endpoint in design.endpoints}

    assert routes == {
        ("POST", "/org/create"),
        ("GET", "/org/{org_id}"),
        ("PATCH", "/org/{org_id}"),
        ("DELETE", "/org/{org_id}"),
    }
    assert design.write_operations_owner_only is True
    assert all(
        endpoint.owner_only_required
        for endpoint in design.endpoints
        if endpoint.method in {"POST", "PATCH", "DELETE"}
    )
    assert design.ui_implemented is False
    assert design.runtime_migration_executed is False


def test_c18a_data_isolation_and_security_boundaries_are_explicit() -> None:
    isolation = get_organization_data_isolation_design()
    security = get_organization_security_boundary()
    completion = get_organization_core_schema_completion_status()

    assert isolation.reserved_partition_key == "org_id"
    assert isolation.all_models_must_reserve_org_id is True
    assert isolation.future_modules_must_bind_org_id == ("C14", "C15", "C17")
    assert isolation.cross_org_default_access_allowed is False
    assert security.owner_absolute_authority is True
    assert security.owner_role_bypass_allowed is False
    assert security.admin_role_can_manage_org_lifecycle is False
    assert security.super_admin_role_can_manage_org_lifecycle is False
    assert security.user_role_can_manage_org_lifecycle is False
    assert security.module_admin_can_manage_org_lifecycle is False
    assert security.delegation_starts_at == "C18D"
    assert completion.organization_schema_defined is True
    assert completion.owner_only_enforcement_defined is True
    assert completion.runtime_migration_executed is False
    assert completion.c17_system_modified is False
