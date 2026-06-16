from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .organization import ORG_ID_PATTERN


CONTACT_IDENTITY_IMMUTABLE_FIELDS = ("name", "org_name", "title")


class ContactIdentityRole(StrEnum):
    OWNER = "owner"
    ORG_ADMIN = "org_admin"
    MEMBER = "member"


class ContactIdentityOperation(StrEnum):
    READ = "read"
    UPDATE = "update"
    CREATE_AT_HIRE_TIME = "create_at_hire_time"


class ContactIdentity(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)

    name: str = Field(min_length=1, max_length=255)
    org_id: str = Field(min_length=1, max_length=40)
    org_name: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)

    role: ContactIdentityRole

    immutable_fields: list[str] = Field(
        default_factory=lambda: list(CONTACT_IDENTITY_IMMUTABLE_FIELDS)
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("user_id", "name", "org_name", "title")
    @classmethod
    def normalize_non_empty_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Contact identity fields must not be empty.")
        return normalized

    @field_validator("org_id")
    @classmethod
    def validate_org_id(cls, value: str) -> str:
        normalized = value.strip()
        if not ORG_ID_PATTERN.fullmatch(normalized):
            raise ValueError("org_id must reference an Organization.org_id.")
        return normalized

    @model_validator(mode="after")
    def validate_contact_identity_shape(self) -> "ContactIdentity":
        if self.immutable_fields != list(CONTACT_IDENTITY_IMMUTABLE_FIELDS):
            raise ValueError(
                "ContactIdentity immutable_fields must be name, org_name, title."
            )
        if self.updated_at < self.created_at:
            raise ValueError("ContactIdentity updated_at must not be before created_at.")
        return self


class ContactIdentityHireInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    org_id: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=255)

    @field_validator("name", "title")
    @classmethod
    def normalize_hire_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Contact identity hire fields must not be empty.")
        return normalized

    @field_validator("org_id")
    @classmethod
    def validate_hire_org_id(cls, value: str) -> str:
        normalized = value.strip()
        if not ORG_ID_PATTERN.fullmatch(normalized):
            raise ValueError("org_id must reference an Organization.org_id.")
        return normalized


class ContactIdentityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    org_name: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("name", "org_name", "title")
    @classmethod
    def normalize_update_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Contact identity update fields must not be empty.")
        return normalized

    @model_validator(mode="after")
    def require_update_field(self) -> "ContactIdentityUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one contact identity field must be supplied.")
        for field_name in self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError("Contact identity update fields must not be null.")
        return self


class ContactIdentityUpdateDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_user_id: str = Field(min_length=1, max_length=255)
    target_user_id: str = Field(min_length=1, max_length=255)
    actor_role: ContactIdentityRole
    actor_org_id: str | None = Field(default=None, max_length=40)
    target_org_id: str = Field(min_length=1, max_length=40)
    target_role: ContactIdentityRole
    requested_fields: tuple[str, ...]
    immutable_fields: tuple[str, str, str] = CONTACT_IDENTITY_IMMUTABLE_FIELDS
    same_org: bool
    allowed: bool
    denied: bool
    denial_code: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_decision(self) -> "ContactIdentityUpdateDecision":
        if self.allowed == self.denied:
            raise ValueError("ContactIdentityUpdateDecision allowed/denied mismatch.")
        if self.allowed and self.denial_code is not None:
            raise ValueError("Allowed contact identity decisions must not be denied.")
        if self.denied and self.denial_code is None:
            raise ValueError("Denied contact identity decisions need denial_code.")
        return self


class ContactIdentityPermissionError(PermissionError):
    pass


def _normalize_requested_fields(
    requested_fields: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for field_name in requested_fields:
        field_value = str(field_name).strip()
        if field_value and field_value not in seen:
            seen.add(field_value)
            normalized.append(field_value)
    return tuple(normalized)


def _role(value: ContactIdentityRole | str) -> ContactIdentityRole:
    return (
        value
        if isinstance(value, ContactIdentityRole)
        else ContactIdentityRole(value)
    )


def evaluate_contact_identity_update(
    *,
    actor_user_id: str | int,
    target_user_id: str | int,
    actor_role: ContactIdentityRole | str,
    actor_org_id: str | None,
    target_org_id: str,
    target_role: ContactIdentityRole | str,
    requested_fields: tuple[str, ...] | list[str],
) -> ContactIdentityUpdateDecision:
    actor = str(actor_user_id).strip() or "[missing_actor_user_id]"
    target = str(target_user_id).strip() or "[missing_target_user_id]"
    actor_role_value = _role(actor_role)
    target_role_value = _role(target_role)
    actor_org = actor_org_id.strip() if actor_org_id is not None else None
    target_org = target_org_id.strip()
    fields = _normalize_requested_fields(requested_fields)
    same_org = actor_org is not None and actor_org == target_org

    def decision(
        *,
        allowed: bool,
        denial_code: str | None,
        reason: str,
    ) -> ContactIdentityUpdateDecision:
        return ContactIdentityUpdateDecision(
            actor_user_id=actor,
            target_user_id=target,
            actor_role=actor_role_value,
            actor_org_id=actor_org,
            target_org_id=target_org,
            target_role=target_role_value,
            requested_fields=fields,
            same_org=same_org,
            allowed=allowed,
            denied=not allowed,
            denial_code=denial_code,
            reason=reason,
        )

    if not fields:
        return decision(
            allowed=False,
            denial_code="c19a_no_identity_fields",
            reason="Contact identity update requires at least one field.",
        )

    invalid_fields = [
        field_name
        for field_name in fields
        if field_name not in CONTACT_IDENTITY_IMMUTABLE_FIELDS
    ]
    if invalid_fields:
        return decision(
            allowed=False,
            denial_code="c19a_non_identity_field_denied",
            reason=(
                "Only name, org_name, and title are mutable through controlled "
                "contact identity updates."
            ),
        )

    if actor_role_value == ContactIdentityRole.OWNER:
        return decision(
            allowed=True,
            denial_code=None,
            reason="Owner may update controlled identity fields for any user.",
        )

    if actor_role_value == ContactIdentityRole.ORG_ADMIN:
        if not same_org:
            return decision(
                allowed=False,
                denial_code="c19a_org_admin_cross_org_denied",
                reason="Org admin cannot update contact identity outside their org.",
            )
        if target_role_value == ContactIdentityRole.OWNER:
            return decision(
                allowed=False,
                denial_code="c19a_org_admin_owner_target_denied",
                reason="Org admin cannot update an owner contact identity.",
            )
        return decision(
            allowed=True,
            denial_code=None,
            reason="Org admin may update controlled fields inside their org.",
        )

    return decision(
        allowed=False,
        denial_code="c19a_member_identity_update_denied",
        reason="Member cannot update any contact identity fields.",
    )


def enforce_contact_identity_update(
    *,
    actor_user_id: str | int,
    target_user_id: str | int,
    actor_role: ContactIdentityRole | str,
    actor_org_id: str | None,
    target_org_id: str,
    target_role: ContactIdentityRole | str,
    requested_fields: tuple[str, ...] | list[str],
) -> ContactIdentityUpdateDecision:
    decision = evaluate_contact_identity_update(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        actor_role=actor_role,
        actor_org_id=actor_org_id,
        target_org_id=target_org_id,
        target_role=target_role,
        requested_fields=requested_fields,
    )
    if decision.denied:
        raise ContactIdentityPermissionError(decision.reason)
    return decision


class ContactIdentityImmutableFieldRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c19a_contact_identity_immutable_fields_v1"] = (
        "c19a_contact_identity_immutable_fields_v1"
    )
    immutable_fields: tuple[
        Literal["name"],
        Literal["org_name"],
        Literal["title"],
    ] = ("name", "org_name", "title")
    only_these_fields_are_patchable: Literal[True] = True
    non_identity_field_update_rule: Literal["DENY UPDATE"] = "DENY UPDATE"
    default_after_create: Literal["locked"] = "locked"


class ContactIdentityRoleUpdateRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: Literal["c19a_contact_identity_role_update_rules_v1"] = (
        "c19a_contact_identity_role_update_rules_v1"
    )
    owner_rule: Literal["owner can update controlled fields across orgs"] = (
        "owner can update controlled fields across orgs"
    )
    org_admin_rule: Literal[
        "org_admin can update controlled fields only in same org and not owner targets"
    ] = "org_admin can update controlled fields only in same org and not owner targets"
    member_rule: Literal["member cannot update identity fields"] = (
        "member cannot update identity fields"
    )
    role_field_patchable: Literal[False] = False
    org_id_field_patchable: Literal[False] = False


class ContactIdentityDatabaseSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["c19a_contact_identities_table_v1"] = (
        "c19a_contact_identities_table_v1"
    )
    table_name: Literal["contact_identities"] = "contact_identities"
    primary_key: Literal["user_id"] = "user_id"
    columns: tuple[
        Literal["user_id"],
        Literal["name"],
        Literal["org_id"],
        Literal["org_name"],
        Literal["title"],
        Literal["role"],
        Literal["created_at"],
        Literal["updated_at"],
    ] = (
        "user_id",
        "name",
        "org_id",
        "org_name",
        "title",
        "role",
        "created_at",
        "updated_at",
    )
    role_check_values: tuple[
        Literal["owner"],
        Literal["org_admin"],
        Literal["member"],
    ] = ("owner", "org_admin", "member")
    migration_executed: Literal[False] = False


class ContactIdentityApiEndpointDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["GET", "PATCH"]
    path: str = Field(min_length=1, max_length=120)
    operation: ContactIdentityOperation
    allowed_roles: tuple[ContactIdentityRole, ...]
    enforces_immutable_fields: bool
    notes: str = Field(min_length=1, max_length=500)


class ContactIdentityApiDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c19a_contact_identity_api_design_v1"] = (
        "c19a_contact_identity_api_design_v1"
    )
    endpoints: tuple[
        ContactIdentityApiEndpointDesign,
        ContactIdentityApiEndpointDesign,
    ] = (
        ContactIdentityApiEndpointDesign(
            method="GET",
            path="/contacts/{user_id}",
            operation=ContactIdentityOperation.READ,
            allowed_roles=(
                ContactIdentityRole.OWNER,
                ContactIdentityRole.ORG_ADMIN,
                ContactIdentityRole.MEMBER,
            ),
            enforces_immutable_fields=False,
            notes="Read requires authentication and same-org visibility unless owner.",
        ),
        ContactIdentityApiEndpointDesign(
            method="PATCH",
            path="/contacts/{user_id}",
            operation=ContactIdentityOperation.UPDATE,
            allowed_roles=(ContactIdentityRole.OWNER, ContactIdentityRole.ORG_ADMIN),
            enforces_immutable_fields=True,
            notes="Patch accepts only name, org_name, and title.",
        ),
    )
    ui_implemented: Literal[False] = False
    chat_implemented: Literal[False] = False


class ContactIdentityIntegrationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c19a_c18_c19_integration_v1"] = (
        "c19a_c18_c19_integration_v1"
    )
    c18c_org_membership_source: Literal["org_memberships"] = "org_memberships"
    c18f_permission_boundary: Literal["service-level identity update decision"] = (
        "service-level identity update decision"
    )
    c19b_global_directory_dependency: Literal[
        "directory may read ContactIdentity snapshots but must not mutate them"
    ] = "directory may read ContactIdentity snapshots but must not mutate them"
    c19c_messaging_dependency: Literal[
        "messaging may display ContactIdentity snapshots but identity is not chat state"
    ] = "messaging may display ContactIdentity snapshots but identity is not chat state"
    implements_c19b: Literal[False] = False
    implements_c19c: Literal[False] = False


class ContactIdentitySecurityModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    security_id: Literal["c19a_contact_identity_security_v1"] = (
        "c19a_contact_identity_security_v1"
    )
    identity_equals_authentication: Literal[False] = False
    stores_passwords_or_tokens: Literal[False] = False
    audit_locked: Literal[True] = True
    ordinary_user_self_service_update_allowed: Literal[False] = False
    all_mutations_traceable: Literal[True] = True
    c17_modified: Literal[False] = False


class ContactIdentityCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19A"] = "C19A"
    component: Literal["Contact Identity System"] = "Contact Identity System"
    completion_status: Literal["complete"] = "complete"
    contact_identity_schema_defined: Literal[True] = True
    immutable_field_enforcement_defined: Literal[True] = True
    role_based_update_rules_defined: Literal[True] = True
    database_schema_defined: Literal[True] = True
    api_design_defined: Literal[True] = True
    c18c_integrated: Literal[True] = True
    c18f_integrated: Literal[True] = True
    c19b_c19c_integration_points_defined: Literal[True] = True
    security_model_defined: Literal[True] = True
    ui_implemented: Literal[False] = False
    chat_implemented: Literal[False] = False
    migration_executed: Literal[False] = False
    c17_modified: Literal[False] = False


CONTACT_IDENTITY_SQL_SCHEMA = """
CREATE TABLE contact_identities (
    user_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    org_id TEXT NOT NULL,
    org_name TEXT NOT NULL,
    title TEXT NOT NULL,
    role TEXT CHECK (role IN ('owner', 'org_admin', 'member')) NOT NULL,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
""".strip()


def get_contact_identity_immutable_field_rules() -> ContactIdentityImmutableFieldRules:
    return ContactIdentityImmutableFieldRules()


def get_contact_identity_role_update_rules() -> ContactIdentityRoleUpdateRules:
    return ContactIdentityRoleUpdateRules()


def get_contact_identity_database_schema() -> ContactIdentityDatabaseSchema:
    return ContactIdentityDatabaseSchema()


def get_contact_identity_api_design() -> ContactIdentityApiDesign:
    return ContactIdentityApiDesign()


def get_contact_identity_integration_model() -> ContactIdentityIntegrationModel:
    return ContactIdentityIntegrationModel()


def get_contact_identity_security_model() -> ContactIdentitySecurityModel:
    return ContactIdentitySecurityModel()


def get_contact_identity_completion_status() -> ContactIdentityCompletionStatus:
    return ContactIdentityCompletionStatus()
