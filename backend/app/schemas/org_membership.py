from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .organization import ORG_ID_PATTERN


ORG_MEMBERSHIP_ID_PATTERN = re.compile(r"^mem_[0-9a-f]{32}$")


class OrgMembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class OrgMembershipStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class OrgMembershipOperation(StrEnum):
    LIST_MEMBERS = "list_members"
    ADD_MEMBER = "add_member"
    REMOVE_MEMBER = "remove_member"
    ORG_ADMIN_OPERATION = "org_admin_operation"
    ORG_LIFECYCLE = "org_lifecycle"
    GLOBAL_SYSTEM_CONTROL = "global_system_control"


def generate_membership_id() -> str:
    return "mem_" + uuid4().hex


class OrgMembership(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    membership_id: str = Field(default_factory=generate_membership_id)
    user_id: str = Field(min_length=1, max_length=255)
    org_id: str = Field(min_length=1, max_length=40)
    role: OrgMembershipRole
    status: OrgMembershipStatus = OrgMembershipStatus.ACTIVE
    joined_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("membership_id")
    @classmethod
    def validate_membership_id(cls, value: str) -> str:
        if not ORG_MEMBERSHIP_ID_PATTERN.fullmatch(value):
            raise ValueError("membership_id must be generated as mem_ + uuid4().hex.")
        return value

    @field_validator("org_id")
    @classmethod
    def validate_org_id(cls, value: str) -> str:
        if not ORG_ID_PATTERN.fullmatch(value):
            raise ValueError("org_id must reference an Organization.org_id.")
        return value

    @model_validator(mode="after")
    def normalize_membership_identity(self) -> "OrgMembership":
        object.__setattr__(self, "user_id", self.user_id.strip())
        object.__setattr__(self, "org_id", self.org_id.strip())
        if not self.user_id:
            raise ValueError("Org membership user_id must not be empty.")
        if not self.org_id:
            raise ValueError("Org membership org_id must not be empty.")
        return self


class OrgMemberAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)
    role: OrgMembershipRole = OrgMembershipRole.MEMBER

    @model_validator(mode="after")
    def normalize_add_request(self) -> "OrgMemberAddRequest":
        self.user_id = self.user_id.strip()
        if not self.user_id:
            raise ValueError("Org member user_id must not be empty.")
        return self


class OrgMemberRemoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def normalize_remove_request(self) -> "OrgMemberRemoveRequest":
        self.user_id = self.user_id.strip()
        if not self.user_id:
            raise ValueError("Org member user_id must not be empty.")
        return self


class OrgMembershipRelationshipModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c18c_org_membership_relationship_v1"] = (
        "c18c_org_membership_relationship_v1"
    )
    user_to_org_cardinality: Literal["many_to_many"] = "many_to_many"
    org_to_user_cardinality: Literal["many_to_many"] = "many_to_many"
    binding_table: Literal["org_memberships"] = "org_memberships"
    user_binding_key: Literal["user_id"] = "user_id"
    org_binding_key: Literal["org_id"] = "org_id"
    membership_is_authoritative_binding: Literal[True] = True
    role_is_scoped_to_membership: Literal[True] = True


class OrgMembershipRoleRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: OrgMembershipRole
    rank: int = Field(ge=1, le=3)
    can_manage_members: bool
    can_manage_org_lifecycle: bool
    can_access_authorized_modules: bool
    grants_global_system_control: Literal[False] = False
    notes: str = Field(min_length=1, max_length=500)


class OrgMembershipRoleHierarchy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hierarchy_id: Literal["c18c_org_role_hierarchy_v1"] = (
        "c18c_org_role_hierarchy_v1"
    )
    roles: tuple[OrgMembershipRoleRule, OrgMembershipRoleRule, OrgMembershipRoleRule] = (
        OrgMembershipRoleRule(
            role=OrgMembershipRole.OWNER,
            rank=3,
            can_manage_members=True,
            can_manage_org_lifecycle=True,
            can_access_authorized_modules=True,
            notes=(
                "Owner is derived from Organization.owner_user_id and has full "
                "organization control only."
            ),
        ),
        OrgMembershipRoleRule(
            role=OrgMembershipRole.ADMIN,
            rank=2,
            can_manage_members=True,
            can_manage_org_lifecycle=False,
            can_access_authorized_modules=True,
            notes=(
                "Admin can manage organization members but cannot modify "
                "organization lifecycle."
            ),
        ),
        OrgMembershipRoleRule(
            role=OrgMembershipRole.MEMBER,
            rank=1,
            can_manage_members=False,
            can_manage_org_lifecycle=False,
            can_access_authorized_modules=True,
            notes="Member is limited to authorized in-organization modules.",
        ),
    )
    owner_source: Literal["Organization.owner_user_id"] = "Organization.owner_user_id"
    exactly_one_owner_per_org: Literal[True] = True
    admin_can_manage_lifecycle: Literal[False] = False
    owner_grants_global_system_control: Literal[False] = False


class OrgMembershipMultiOrgUserModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: Literal["c18c_multi_org_user_model_v1"] = (
        "c18c_multi_org_user_model_v1"
    )
    user_can_join_multiple_orgs: Literal[True] = True
    org_can_have_multiple_users: Literal[True] = True
    role_can_differ_per_org: Literal[True] = True
    example_user_a_org_1_role: Literal[OrgMembershipRole.ADMIN] = (
        OrgMembershipRole.ADMIN
    )
    example_user_a_org_2_role: Literal[OrgMembershipRole.MEMBER] = (
        OrgMembershipRole.MEMBER
    )


class OrgMembershipApiEndpointDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["POST", "GET"]
    path: str = Field(min_length=1, max_length=140)
    operation: OrgMembershipOperation
    allowed_roles: tuple[OrgMembershipRole, ...]
    org_id_filter_required: Literal[True] = True
    cross_org_leakage_allowed: Literal[False] = False
    notes: str = Field(min_length=1, max_length=500)


class OrgMembershipApiDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c18c_membership_api_design_v1"] = (
        "c18c_membership_api_design_v1"
    )
    endpoints: tuple[
        OrgMembershipApiEndpointDesign,
        OrgMembershipApiEndpointDesign,
        OrgMembershipApiEndpointDesign,
    ] = (
        OrgMembershipApiEndpointDesign(
            method="POST",
            path="/org/{org_id}/members/add",
            operation=OrgMembershipOperation.ADD_MEMBER,
            allowed_roles=(OrgMembershipRole.OWNER, OrgMembershipRole.ADMIN),
            notes="Add member requires active owner or admin membership in org_id.",
        ),
        OrgMembershipApiEndpointDesign(
            method="POST",
            path="/org/{org_id}/members/remove",
            operation=OrgMembershipOperation.REMOVE_MEMBER,
            allowed_roles=(OrgMembershipRole.OWNER, OrgMembershipRole.ADMIN),
            notes="Remove member requires active owner or admin membership in org_id.",
        ),
        OrgMembershipApiEndpointDesign(
            method="GET",
            path="/org/{org_id}/members",
            operation=OrgMembershipOperation.LIST_MEMBERS,
            allowed_roles=(
                OrgMembershipRole.OWNER,
                OrgMembershipRole.ADMIN,
                OrgMembershipRole.MEMBER,
            ),
            notes="List members is always filtered by org_id and requires org membership.",
        ),
    )
    ui_implemented: Literal[False] = False
    module_binding_implemented: Literal[False] = False
    c17_system_connected: Literal[False] = False
    runtime_migration_executed: Literal[True] = True


class OrgMembershipDatabaseSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["c18c_org_memberships_table_v1"] = (
        "c18c_org_memberships_table_v1"
    )
    table_name: Literal["org_memberships"] = "org_memberships"
    primary_key: Literal["membership_id"] = "membership_id"
    binding_columns: tuple[Literal["user_id"], Literal["org_id"]] = (
        "user_id",
        "org_id",
    )
    required_indexes: tuple[
        Literal["user_id_org_id"],
        Literal["org_id"],
        Literal["org_id_status"],
    ] = ("user_id_org_id", "org_id", "org_id_status")
    user_id_org_id_pair_is_unique: Literal[True] = True
    role_check_values: tuple[
        Literal["owner"],
        Literal["admin"],
        Literal["member"],
    ] = ("owner", "admin", "member")
    status_check_values: tuple[Literal["active"], Literal["suspended"]] = (
        "active",
        "suspended",
    )


class OrgMembershipPermissionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_user_id: str = Field(min_length=1, max_length=255)
    org_id: str = Field(min_length=1, max_length=40)
    operation: OrgMembershipOperation
    role: OrgMembershipRole | None = None
    status: OrgMembershipStatus | None = None
    allowed: bool
    denied: bool
    denial_code: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1, max_length=500)
    org_id_filter_required: Literal[True] = True
    grants_global_system_control: Literal[False] = False


class OrgMembershipPermissionError(PermissionError):
    pass


def evaluate_org_membership_permission(
    *,
    actor_user_id: str | int,
    org_id: str,
    operation: OrgMembershipOperation | str,
    role: OrgMembershipRole | str | None,
    status: OrgMembershipStatus | str | None,
) -> OrgMembershipPermissionDecision:
    actor = str(actor_user_id).strip()
    scoped_org_id = org_id.strip()
    membership_operation = OrgMembershipOperation(operation)

    def decision(
        *,
        allowed: bool,
        denial_code: str | None,
        reason: str,
        role_value: OrgMembershipRole | None = None,
        status_value: OrgMembershipStatus | None = None,
    ) -> OrgMembershipPermissionDecision:
        return OrgMembershipPermissionDecision(
            actor_user_id=actor or "[missing_actor_user_id]",
            org_id=scoped_org_id,
            operation=membership_operation,
            role=role_value,
            status=status_value,
            allowed=allowed,
            denied=not allowed,
            denial_code=denial_code,
            reason=reason,
        )

    if membership_operation == OrgMembershipOperation.GLOBAL_SYSTEM_CONTROL:
        return decision(
            allowed=False,
            denial_code="c18c_global_control_denied",
            reason="Organization membership never grants global system control.",
        )

    if not actor or role is None or status is None:
        return decision(
            allowed=False,
            denial_code="c18c_user_not_in_org",
            reason="Access denied because actor_user_id has no membership in org_id.",
        )

    role_value = OrgMembershipRole(role)
    status_value = OrgMembershipStatus(status)
    if status_value != OrgMembershipStatus.ACTIVE:
        return decision(
            allowed=False,
            denial_code="c18c_membership_not_active",
            reason="Access denied because organization membership is not active.",
            role_value=role_value,
            status_value=status_value,
        )

    if role_value == OrgMembershipRole.OWNER:
        return decision(
            allowed=True,
            denial_code=None,
            reason="Owner membership allows organization-scoped operation.",
            role_value=role_value,
            status_value=status_value,
        )

    if membership_operation == OrgMembershipOperation.ORG_LIFECYCLE:
        return decision(
            allowed=False,
            denial_code="c18c_lifecycle_owner_only",
            reason="Organization lifecycle control is owner-only and not delegated.",
            role_value=role_value,
            status_value=status_value,
        )

    if role_value == OrgMembershipRole.ADMIN:
        return decision(
            allowed=True,
            denial_code=None,
            reason="Admin membership allows organization member management.",
            role_value=role_value,
            status_value=status_value,
        )

    if membership_operation == OrgMembershipOperation.LIST_MEMBERS:
        return decision(
            allowed=True,
            denial_code=None,
            reason="Active member can list members within the same org_id.",
            role_value=role_value,
            status_value=status_value,
        )

    return decision(
        allowed=False,
        denial_code="c18c_member_admin_operation_denied",
        reason="Member role cannot perform organization admin operations.",
        role_value=role_value,
        status_value=status_value,
    )


def enforce_org_membership_permission(
    *,
    actor_user_id: str | int,
    org_id: str,
    operation: OrgMembershipOperation | str,
    role: OrgMembershipRole | str | None,
    status: OrgMembershipStatus | str | None,
) -> OrgMembershipPermissionDecision:
    decision = evaluate_org_membership_permission(
        actor_user_id=actor_user_id,
        org_id=org_id,
        operation=operation,
        role=role,
        status=status,
    )
    if decision.denied:
        raise OrgMembershipPermissionError(decision.reason)
    return decision


class OrgMembershipIsolationGuarantees(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    guarantee_id: Literal["c18c_org_membership_isolation_v1"] = (
        "c18c_org_membership_isolation_v1"
    )
    membership_must_bind_org_id: Literal[True] = True
    every_membership_query_filters_org_id: Literal[True] = True
    cross_org_membership_leakage_allowed: Literal[False] = False
    user_id_org_id_pair_is_unique: Literal[True] = True
    suspended_membership_counts_as_not_in_org: Literal[True] = True
    cross_org_query_logic_extended: Literal[False] = False


class OrgMembershipCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C18C"] = "C18C"
    component: Literal["Org Membership System"] = "Org Membership System"
    completion_status: Literal["complete"] = "complete"
    org_membership_schema_defined: Literal[True] = True
    membership_relationship_model_defined: Literal[True] = True
    role_hierarchy_defined: Literal[True] = True
    multi_org_user_model_defined: Literal[True] = True
    api_design_defined: Literal[True] = True
    database_schema_defined: Literal[True] = True
    permission_enforcement_defined: Literal[True] = True
    isolation_guarantees_defined: Literal[True] = True
    ui_implemented: Literal[False] = False
    module_binding_implemented: Literal[False] = False
    c17_system_connected: Literal[False] = False
    runtime_migration_executed: Literal[True] = True


ORG_MEMBERSHIP_SQL_SCHEMA = """
CREATE TABLE org_memberships (
    membership_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    role TEXT CHECK (role IN ('owner', 'admin', 'member')),
    status TEXT CHECK (status IN ('active', 'suspended')),
    joined_at TIMESTAMP,
    created_at TIMESTAMP,
    FOREIGN KEY (org_id) REFERENCES organizations (org_id)
);

CREATE UNIQUE INDEX ix_org_memberships_user_id_org_id
    ON org_memberships (user_id, org_id);

CREATE INDEX ix_org_memberships_org_id
    ON org_memberships (org_id);

CREATE INDEX ix_org_memberships_org_id_status
    ON org_memberships (org_id, status);
""".strip()


def get_org_membership_relationship_model() -> OrgMembershipRelationshipModel:
    return OrgMembershipRelationshipModel()


def get_org_membership_role_hierarchy() -> OrgMembershipRoleHierarchy:
    return OrgMembershipRoleHierarchy()


def get_org_membership_multi_org_user_model() -> OrgMembershipMultiOrgUserModel:
    return OrgMembershipMultiOrgUserModel()


def get_org_membership_api_design() -> OrgMembershipApiDesign:
    return OrgMembershipApiDesign()


def get_org_membership_database_schema() -> OrgMembershipDatabaseSchema:
    return OrgMembershipDatabaseSchema()


def get_org_membership_isolation_guarantees() -> OrgMembershipIsolationGuarantees:
    return OrgMembershipIsolationGuarantees()


def get_org_membership_completion_status() -> OrgMembershipCompletionStatus:
    return OrgMembershipCompletionStatus()
