from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from backend.app.schemas.contact_identity import (
    CONTACT_IDENTITY_SQL_SCHEMA,
    ContactIdentity,
    ContactIdentityPermissionError,
    ContactIdentityRole,
    ContactIdentityUpdate,
    enforce_contact_identity_update,
    evaluate_contact_identity_update,
    get_contact_identity_api_design,
    get_contact_identity_completion_status,
    get_contact_identity_database_schema,
    get_contact_identity_immutable_field_rules,
    get_contact_identity_integration_model,
    get_contact_identity_role_update_rules,
    get_contact_identity_security_model,
)
from backend.app.schemas.organization import generate_org_id


def test_c19a_contact_identity_schema_defines_locked_identity_shape() -> None:
    org_id = generate_org_id()
    identity = ContactIdentity(
        user_id=" user-1 ",
        name=" Alice Ops ",
        org_id=org_id,
        org_name=" Barong Store ",
        title=" Operations Lead ",
        role=ContactIdentityRole.ORG_ADMIN,
    )

    assert identity.user_id == "user-1"
    assert identity.name == "Alice Ops"
    assert identity.org_id == org_id
    assert identity.org_name == "Barong Store"
    assert identity.title == "Operations Lead"
    assert identity.role == "org_admin"
    assert identity.immutable_fields == ["name", "org_name", "title"]
    assert identity.created_at is not None
    assert identity.updated_at is not None

    with pytest.raises(ValidationError):
        ContactIdentity(
            user_id="user-1",
            name="Alice Ops",
            org_id="bad-org",
            org_name="Barong Store",
            title="Operations Lead",
            role="member",
        )

    with pytest.raises(ValidationError):
        ContactIdentity(
            user_id="user-1",
            name="Alice Ops",
            org_id=org_id,
            org_name="Barong Store",
            title="Operations Lead",
            role="admin",
        )


def test_c19a_update_payload_accepts_only_identity_fields() -> None:
    payload = ContactIdentityUpdate(name=" Alice ", title=" Director ")
    assert payload.name == "Alice"
    assert payload.title == "Director"

    with pytest.raises(ValidationError):
        ContactIdentityUpdate()

    with pytest.raises(ValidationError):
        ContactIdentityUpdate(title=None)

    with pytest.raises(ValidationError):
        ContactIdentityUpdate(role="owner")


def test_c19a_identity_update_decision_enforces_role_rules() -> None:
    org_a = generate_org_id()
    org_b = generate_org_id()

    owner = evaluate_contact_identity_update(
        actor_user_id="owner-1",
        target_user_id="member-1",
        actor_role="owner",
        actor_org_id=None,
        target_org_id=org_b,
        target_role="member",
        requested_fields=("name", "org_name", "title"),
    )
    assert owner.allowed is True

    org_admin_same_org = enforce_contact_identity_update(
        actor_user_id="admin-1",
        target_user_id="member-1",
        actor_role="org_admin",
        actor_org_id=org_a,
        target_org_id=org_a,
        target_role="member",
        requested_fields=("title",),
    )
    assert org_admin_same_org.allowed is True

    org_admin_cross_org = evaluate_contact_identity_update(
        actor_user_id="admin-1",
        target_user_id="member-2",
        actor_role="org_admin",
        actor_org_id=org_a,
        target_org_id=org_b,
        target_role="member",
        requested_fields=("title",),
    )
    assert org_admin_cross_org.denied is True
    assert org_admin_cross_org.denial_code == "c19a_org_admin_cross_org_denied"

    org_admin_owner_target = evaluate_contact_identity_update(
        actor_user_id="admin-1",
        target_user_id="owner-1",
        actor_role="org_admin",
        actor_org_id=org_a,
        target_org_id=org_a,
        target_role="owner",
        requested_fields=("name",),
    )
    assert org_admin_owner_target.denied is True
    assert org_admin_owner_target.denial_code == "c19a_org_admin_owner_target_denied"

    member_update = evaluate_contact_identity_update(
        actor_user_id="member-1",
        target_user_id="member-1",
        actor_role="member",
        actor_org_id=org_a,
        target_org_id=org_a,
        target_role="member",
        requested_fields=("title",),
    )
    assert member_update.denied is True
    assert member_update.denial_code == "c19a_member_identity_update_denied"

    invalid_field = evaluate_contact_identity_update(
        actor_user_id="owner-1",
        target_user_id="member-1",
        actor_role="owner",
        actor_org_id=None,
        target_org_id=org_a,
        target_role="member",
        requested_fields=("role",),
    )
    assert invalid_field.denied is True
    assert invalid_field.denial_code == "c19a_non_identity_field_denied"

    with pytest.raises(ContactIdentityPermissionError):
        enforce_contact_identity_update(
            actor_user_id="member-1",
            target_user_id="member-2",
            actor_role="member",
            actor_org_id=org_a,
            target_org_id=org_a,
            target_role="member",
            requested_fields=("name",),
        )


def test_c19a_design_outputs_match_required_contract() -> None:
    immutable = get_contact_identity_immutable_field_rules()
    role_rules = get_contact_identity_role_update_rules()
    database = get_contact_identity_database_schema()
    api = get_contact_identity_api_design()
    integration = get_contact_identity_integration_model()
    security = get_contact_identity_security_model()
    completion = get_contact_identity_completion_status()
    compact_sql = re.sub(r"\s+", " ", CONTACT_IDENTITY_SQL_SCHEMA)

    assert immutable.immutable_fields == ("name", "org_name", "title")
    assert immutable.non_identity_field_update_rule == "DENY UPDATE"
    assert role_rules.role_field_patchable is False
    assert role_rules.org_id_field_patchable is False
    assert database.table_name == "contact_identities"
    assert database.primary_key == "user_id"
    assert database.role_check_values == ("owner", "org_admin", "member")
    assert database.migration_executed is False
    assert "CREATE TABLE contact_identities" in CONTACT_IDENTITY_SQL_SCHEMA
    assert "user_id TEXT PRIMARY KEY" in compact_sql
    assert "name TEXT NOT NULL" in compact_sql
    assert "org_id TEXT NOT NULL" in compact_sql
    assert "org_name TEXT NOT NULL" in compact_sql
    assert "title TEXT NOT NULL" in compact_sql
    assert "role TEXT CHECK" in compact_sql
    assert "'org_admin'" in compact_sql

    routes = {(endpoint.method, endpoint.path) for endpoint in api.endpoints}
    assert routes == {
        ("GET", "/contacts/{user_id}"),
        ("PATCH", "/contacts/{user_id}"),
    }
    assert api.ui_implemented is False
    assert api.chat_implemented is False
    assert integration.c18c_org_membership_source == "org_memberships"
    assert integration.implements_c19b is False
    assert integration.implements_c19c is False
    assert security.identity_equals_authentication is False
    assert security.ordinary_user_self_service_update_allowed is False
    assert security.c17_modified is False
    assert completion.contact_identity_schema_defined is True
    assert completion.immutable_field_enforcement_defined is True
    assert completion.migration_executed is False
