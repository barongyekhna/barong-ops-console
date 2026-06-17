from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from backend.app.schemas.org_membership import (
    ORG_MEMBERSHIP_SQL_SCHEMA,
    OrgMembership,
    OrgMembershipOperation,
    OrgMembershipPermissionError,
    OrgMembershipRole,
    OrgMembershipStatus,
    enforce_org_membership_permission,
    evaluate_org_membership_permission,
    generate_membership_id,
    get_org_membership_api_design,
    get_org_membership_completion_status,
    get_org_membership_database_schema,
    get_org_membership_isolation_guarantees,
    get_org_membership_multi_org_user_model,
    get_org_membership_relationship_model,
    get_org_membership_role_hierarchy,
)
from backend.app.schemas.organization import generate_org_id


def test_c18c_org_membership_schema_defines_core_binding_model() -> None:
    membership = OrgMembership(
        membership_id=generate_membership_id(),
        user_id=" user-1 ",
        org_id=generate_org_id(),
        role=OrgMembershipRole.ADMIN,
    )

    assert membership.membership_id.startswith("mem_")
    assert membership.user_id == "user-1"
    assert membership.role == "admin"
    assert membership.status == "active"
    assert membership.joined_at is not None

    with pytest.raises(ValidationError):
        OrgMembership(
            membership_id="bad-id",
            user_id="user-1",
            org_id=generate_org_id(),
            role="member",
        )

    with pytest.raises(ValidationError):
        OrgMembership(
            user_id="user-1",
            org_id="not-an-org-id",
            role="member",
        )


def test_c18c_relationship_role_and_multi_org_models_are_explicit() -> None:
    relationship = get_org_membership_relationship_model()
    hierarchy = get_org_membership_role_hierarchy()
    multi_org = get_org_membership_multi_org_user_model()

    assert relationship.binding_table == "org_memberships"
    assert relationship.user_to_org_cardinality == "many_to_many"
    assert relationship.org_to_user_cardinality == "many_to_many"
    assert relationship.role_is_scoped_to_membership is True

    rules = {rule.role: rule for rule in hierarchy.roles}
    assert rules[OrgMembershipRole.OWNER].can_manage_members is True
    assert rules[OrgMembershipRole.OWNER].can_manage_org_lifecycle is True
    assert rules[OrgMembershipRole.ADMIN].can_manage_members is True
    assert rules[OrgMembershipRole.ADMIN].can_manage_org_lifecycle is False
    assert rules[OrgMembershipRole.MEMBER].can_manage_members is False
    assert hierarchy.exactly_one_owner_per_org is True
    assert hierarchy.owner_source == "Organization.owner_user_id"

    assert multi_org.user_can_join_multiple_orgs is True
    assert multi_org.org_can_have_multiple_users is True
    assert multi_org.role_can_differ_per_org is True
    assert multi_org.example_user_a_org_1_role == "admin"
    assert multi_org.example_user_a_org_2_role == "member"


def test_c18c_permission_enforcement_matches_role_hierarchy() -> None:
    org_id = generate_org_id()

    not_in_org = evaluate_org_membership_permission(
        actor_user_id="user-1",
        org_id=org_id,
        operation=OrgMembershipOperation.LIST_MEMBERS,
        role=None,
        status=None,
    )
    assert not_in_org.denied is True
    assert not_in_org.denial_code == "c18c_user_not_in_org"

    member_admin = evaluate_org_membership_permission(
        actor_user_id="user-1",
        org_id=org_id,
        operation=OrgMembershipOperation.ADD_MEMBER,
        role=OrgMembershipRole.MEMBER,
        status=OrgMembershipStatus.ACTIVE,
    )
    assert member_admin.denied is True
    assert member_admin.denial_code == "c18c_member_admin_operation_denied"

    admin_add = enforce_org_membership_permission(
        actor_user_id="user-2",
        org_id=org_id,
        operation=OrgMembershipOperation.ADD_MEMBER,
        role=OrgMembershipRole.ADMIN,
        status=OrgMembershipStatus.ACTIVE,
    )
    assert admin_add.allowed is True

    admin_lifecycle = evaluate_org_membership_permission(
        actor_user_id="user-2",
        org_id=org_id,
        operation=OrgMembershipOperation.ORG_LIFECYCLE,
        role=OrgMembershipRole.ADMIN,
        status=OrgMembershipStatus.ACTIVE,
    )
    assert admin_lifecycle.denied is True
    assert admin_lifecycle.denial_code == "c18c_lifecycle_owner_only"

    owner_global = evaluate_org_membership_permission(
        actor_user_id="owner-1",
        org_id=org_id,
        operation=OrgMembershipOperation.GLOBAL_SYSTEM_CONTROL,
        role=OrgMembershipRole.OWNER,
        status=OrgMembershipStatus.ACTIVE,
    )
    assert owner_global.denied is True
    assert owner_global.denial_code == "c18c_global_control_denied"

    with pytest.raises(OrgMembershipPermissionError):
        enforce_org_membership_permission(
            actor_user_id="user-3",
            org_id=org_id,
            operation=OrgMembershipOperation.REMOVE_MEMBER,
            role=OrgMembershipRole.MEMBER,
            status=OrgMembershipStatus.ACTIVE,
        )


def test_c18c_api_database_and_isolation_design_match_required_contract() -> None:
    api_design = get_org_membership_api_design()
    database = get_org_membership_database_schema()
    isolation = get_org_membership_isolation_guarantees()
    completion = get_org_membership_completion_status()
    compact_sql = re.sub(r"\s+", " ", ORG_MEMBERSHIP_SQL_SCHEMA)

    routes = {(endpoint.method, endpoint.path) for endpoint in api_design.endpoints}
    assert routes == {
        ("POST", "/org/{org_id}/members/add"),
        ("POST", "/org/{org_id}/members/remove"),
        ("GET", "/org/{org_id}/members"),
    }
    assert all(endpoint.org_id_filter_required for endpoint in api_design.endpoints)
    assert all(
        endpoint.cross_org_leakage_allowed is False
        for endpoint in api_design.endpoints
    )
    assert api_design.ui_implemented is False
    assert api_design.module_binding_implemented is False
    assert api_design.c17_system_connected is False
    assert api_design.runtime_migration_executed is True

    assert database.table_name == "org_memberships"
    assert database.binding_columns == ("user_id", "org_id")
    assert database.required_indexes == ("user_id_org_id", "org_id", "org_id_status")
    assert database.user_id_org_id_pair_is_unique is True
    assert "CREATE TABLE org_memberships" in ORG_MEMBERSHIP_SQL_SCHEMA
    assert "membership_id TEXT PRIMARY KEY" in compact_sql
    assert "user_id TEXT NOT NULL" in compact_sql
    assert "org_id TEXT NOT NULL" in compact_sql
    assert "role TEXT CHECK" in compact_sql
    assert "'owner'" in compact_sql
    assert "'admin'" in compact_sql
    assert "'member'" in compact_sql
    assert "status TEXT CHECK" in compact_sql
    assert "'active'" in compact_sql
    assert "'suspended'" in compact_sql
    assert "joined_at TIMESTAMP" in compact_sql
    assert "created_at TIMESTAMP" in compact_sql
    assert "FOREIGN KEY (org_id) REFERENCES organizations (org_id)" in compact_sql
    assert "ix_org_memberships_user_id_org_id" in compact_sql
    assert "ix_org_memberships_org_id" in compact_sql
    assert "ix_org_memberships_org_id_status" in compact_sql

    assert isolation.membership_must_bind_org_id is True
    assert isolation.every_membership_query_filters_org_id is True
    assert isolation.cross_org_membership_leakage_allowed is False
    assert isolation.suspended_membership_counts_as_not_in_org is True
    assert isolation.cross_org_query_logic_extended is False
    assert completion.org_membership_schema_defined is True
    assert completion.permission_enforcement_defined is True
    assert completion.runtime_migration_executed is True
