from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ORG_ID_PATTERN = re.compile(r"^org_[0-9a-f]{32}$")
ORG_CORE_IDENTITY_FIELDS = ("org_id", "org_name", "org_type", "owner_user_id")


class OrganizationType(StrEnum):
    STORE = "store"
    FACTORY = "factory"
    WAREHOUSE = "warehouse"


class OrganizationStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class OrganizationLifecycleOperation(StrEnum):
    CREATE = "create"
    DELETE = "delete"
    RENAME = "rename"
    UPDATE_CORE_FIELDS = "update_core_fields"


def generate_org_id() -> str:
    return "org_" + uuid4().hex


class OrganizationMetadataSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_ai: bool = False
    allow_n8n: bool = False
    data_retention_days: int = Field(default=365, ge=1)


class OrganizationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    industry: str = Field(default="", max_length=120)
    country: str = Field(default="", max_length=120)
    timezone: str = Field(default="UTC", min_length=1, max_length=120)
    settings: OrganizationMetadataSettings = Field(
        default_factory=OrganizationMetadataSettings
    )
    custom: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def strip_metadata_strings(self) -> "OrganizationMetadata":
        self.industry = self.industry.strip()
        self.country = self.country.strip()
        self.timezone = self.timezone.strip()
        if not self.timezone:
            raise ValueError("Organization timezone must not be empty.")
        return self


class Organization(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    org_id: str = Field(default_factory=generate_org_id)
    org_name: str = Field(min_length=1, max_length=255)
    org_type: OrganizationType
    status: OrganizationStatus = OrganizationStatus.ACTIVE
    owner_user_id: str = Field(min_length=1, max_length=255)
    metadata: OrganizationMetadata = Field(default_factory=OrganizationMetadata)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("org_id")
    @classmethod
    def validate_org_id(cls, value: str) -> str:
        if not ORG_ID_PATTERN.fullmatch(value):
            raise ValueError("org_id must be generated as org_ + uuid4().hex.")
        return value

    @model_validator(mode="after")
    def normalize_identity_strings(self) -> "Organization":
        object.__setattr__(self, "org_name", self.org_name.strip())
        object.__setattr__(self, "owner_user_id", self.owner_user_id.strip())
        if not self.org_name:
            raise ValueError("Organization name must not be empty.")
        if not self.owner_user_id:
            raise ValueError("Organization owner_user_id must not be empty.")
        if self.updated_at < self.created_at:
            raise ValueError("Organization updated_at must not be before created_at.")
        return self


class OrgScopedModelMixin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_id: str = Field(min_length=1, max_length=40)

    @field_validator("org_id")
    @classmethod
    def validate_scoped_org_id(cls, value: str) -> str:
        if not ORG_ID_PATTERN.fullmatch(value):
            raise ValueError("org_id must reference an Organization.org_id.")
        return value


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_name: str = Field(min_length=1, max_length=255)
    org_type: OrganizationType
    owner_user_id: str = Field(min_length=1, max_length=255)
    metadata: OrganizationMetadata = Field(default_factory=OrganizationMetadata)

    @model_validator(mode="after")
    def strip_identity_strings(self) -> "OrganizationCreate":
        self.org_name = self.org_name.strip()
        self.owner_user_id = self.owner_user_id.strip()
        if not self.org_name:
            raise ValueError("Organization name must not be empty.")
        if not self.owner_user_id:
            raise ValueError("Organization owner_user_id must not be empty.")
        return self


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_name: str | None = Field(default=None, min_length=1, max_length=255)
    org_type: OrganizationType | None = None
    owner_user_id: str | None = Field(default=None, min_length=1, max_length=255)
    status: OrganizationStatus | None = None
    metadata: OrganizationMetadata | None = None

    @model_validator(mode="after")
    def require_update_field(self) -> "OrganizationUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one organization field must be supplied.")
        if self.org_name is not None:
            self.org_name = self.org_name.strip()
            if not self.org_name:
                raise ValueError("Organization name must not be empty.")
        if self.owner_user_id is not None:
            self.owner_user_id = self.owner_user_id.strip()
            if not self.owner_user_id:
                raise ValueError("Organization owner_user_id must not be empty.")
        return self


class OrganizationTypeRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    org_type: OrganizationType
    domain: str = Field(min_length=1, max_length=255)
    allowed_scope: str = Field(min_length=1, max_length=500)


class OrganizationTypeConstraintSystem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    system_id: Literal["c18a_org_type_constraints_v1"] = (
        "c18a_org_type_constraints_v1"
    )
    rules: tuple[OrganizationTypeRule, ...] = (
        OrganizationTypeRule(
            org_type=OrganizationType.STORE,
            domain="independent storefront business",
            allowed_scope="SEO / K-series / P-series independent site operations",
        ),
        OrganizationTypeRule(
            org_type=OrganizationType.FACTORY,
            domain="factory production system",
            allowed_scope="factory production and manufacturing operations",
        ),
        OrganizationTypeRule(
            org_type=OrganizationType.WAREHOUSE,
            domain="warehouse logistics system",
            allowed_scope="warehouse inventory, fulfillment, and logistics operations",
        ),
    )


class OrganizationApiEndpointDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["POST", "GET", "PATCH", "DELETE"]
    path: str = Field(min_length=1, max_length=120)
    lifecycle_operation: OrganizationLifecycleOperation | Literal["read"]
    owner_only_required: bool
    notes: str = Field(min_length=1, max_length=500)


class OrganizationApiDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c18a_organization_api_design_v1"] = (
        "c18a_organization_api_design_v1"
    )
    endpoints: tuple[OrganizationApiEndpointDesign, ...] = (
        OrganizationApiEndpointDesign(
            method="POST",
            path="/org/create",
            lifecycle_operation=OrganizationLifecycleOperation.CREATE,
            owner_only_required=True,
            notes=(
                "Create is allowed only when actor_user_id equals payload.owner_user_id."
            ),
        ),
        OrganizationApiEndpointDesign(
            method="GET",
            path="/org/{org_id}",
            lifecycle_operation="read",
            owner_only_required=False,
            notes=(
                "Read design is org-scoped; cross-org default access is not allowed."
            ),
        ),
        OrganizationApiEndpointDesign(
            method="PATCH",
            path="/org/{org_id}",
            lifecycle_operation=OrganizationLifecycleOperation.UPDATE_CORE_FIELDS,
            owner_only_required=True,
            notes=(
                "Rename and core field updates require actor_user_id to equal "
                "current organization owner_user_id."
            ),
        ),
        OrganizationApiEndpointDesign(
            method="DELETE",
            path="/org/{org_id}",
            lifecycle_operation=OrganizationLifecycleOperation.DELETE,
            owner_only_required=True,
            notes=(
                "Delete requires actor_user_id to equal current organization "
                "owner_user_id."
            ),
        ),
    )
    write_operations_owner_only: Literal[True] = True
    ui_implemented: Literal[False] = False
    runtime_migration_executed: Literal[False] = False


class OrganizationLifecycleAccessDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_user_id: str = Field(min_length=1, max_length=255)
    owner_user_id: str = Field(min_length=1, max_length=255)
    operation: OrganizationLifecycleOperation
    allowed: bool
    denied: bool
    denial_code: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1, max_length=500)
    owner_only_lifecycle_control: Literal[True] = True
    role_delegation_allowed: Literal[False] = False


class OrganizationLifecyclePermissionError(PermissionError):
    pass


def _normalize_user_id(value: str | int) -> str:
    return str(value).strip()


def evaluate_owner_only_org_lifecycle_access(
    *,
    actor_user_id: str | int,
    owner_user_id: str | int,
    operation: OrganizationLifecycleOperation | str,
) -> OrganizationLifecycleAccessDecision:
    actor = _normalize_user_id(actor_user_id)
    owner = _normalize_user_id(owner_user_id)
    lifecycle_operation = OrganizationLifecycleOperation(operation)

    if not actor or not owner or actor != owner:
        return OrganizationLifecycleAccessDecision(
            actor_user_id=actor or "[missing_actor_user_id]",
            owner_user_id=owner or "[missing_owner_user_id]",
            operation=lifecycle_operation,
            allowed=False,
            denied=True,
            denial_code="c18a_owner_only_org_lifecycle_denied",
            reason=(
                "Organization lifecycle management is denied because "
                "actor_user_id must equal owner_user_id. No role grants this "
                "authority."
            ),
        )

    return OrganizationLifecycleAccessDecision(
        actor_user_id=actor,
        owner_user_id=owner,
        operation=lifecycle_operation,
        allowed=True,
        denied=False,
        denial_code=None,
        reason=(
            "Organization lifecycle management is allowed because "
            "actor_user_id equals owner_user_id."
        ),
    )


def enforce_owner_only_org_lifecycle(
    *,
    actor_user_id: str | int,
    owner_user_id: str | int,
    operation: OrganizationLifecycleOperation | str,
) -> OrganizationLifecycleAccessDecision:
    decision = evaluate_owner_only_org_lifecycle_access(
        actor_user_id=actor_user_id,
        owner_user_id=owner_user_id,
        operation=operation,
    )
    if decision.denied:
        raise OrganizationLifecyclePermissionError(decision.reason)
    return decision


def enforce_owner_can_create_organization(
    *,
    actor_user_id: str | int,
    payload: OrganizationCreate,
) -> OrganizationLifecycleAccessDecision:
    return enforce_owner_only_org_lifecycle(
        actor_user_id=actor_user_id,
        owner_user_id=payload.owner_user_id,
        operation=OrganizationLifecycleOperation.CREATE,
    )


class OrganizationDataIsolationDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c18a_org_data_isolation_v1"] = (
        "c18a_org_data_isolation_v1"
    )
    reserved_partition_key: Literal["org_id"] = "org_id"
    all_models_must_reserve_org_id: Literal[True] = True
    future_modules_must_bind_org_id: tuple[
        Literal["C14"],
        Literal["C15"],
        Literal["C17"],
    ] = ("C14", "C15", "C17")
    cross_org_default_access_allowed: Literal[False] = False
    module_binding_implemented_in_c18a: Literal[False] = False
    permission_system_implemented_in_c18a: Literal[False] = False


class OrganizationSecurityBoundary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    boundary_id: Literal["c18a_org_security_boundary_v1"] = (
        "c18a_org_security_boundary_v1"
    )
    owner_absolute_authority: Literal[True] = True
    owner_user_id_controls_lifecycle: Literal[True] = True
    owner_role_bypass_allowed: Literal[False] = False
    admin_role_can_manage_org_lifecycle: Literal[False] = False
    super_admin_role_can_manage_org_lifecycle: Literal[False] = False
    user_role_can_manage_org_lifecycle: Literal[False] = False
    module_admin_can_manage_org_lifecycle: Literal[False] = False
    org_structure_delegated: Literal[False] = False
    delegation_starts_at: Literal["C18D"] = "C18D"
    rule: Literal["if user != owner_user_id: DENY ALL org management operations"] = (
        "if user != owner_user_id: DENY ALL org management operations"
    )


class OrganizationCoreSchemaCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C18A"] = "C18A"
    component: Literal["Organization Core Schema"] = "Organization Core Schema"
    completion_status: Literal["complete"] = "complete"
    organization_schema_defined: Literal[True] = True
    org_id_generator_defined: Literal[True] = True
    org_type_enum_defined: Literal[True] = True
    metadata_structure_defined: Literal[True] = True
    sql_schema_defined: Literal[True] = True
    api_design_defined: Literal[True] = True
    owner_only_enforcement_defined: Literal[True] = True
    security_boundary_defined: Literal[True] = True
    ui_implemented: Literal[False] = False
    module_binding_implemented: Literal[False] = False
    permission_system_implemented: Literal[False] = False
    cross_org_query_logic_implemented: Literal[False] = False
    runtime_migration_executed: Literal[False] = False
    c17_system_modified: Literal[False] = False


ORGANIZATION_SQL_SCHEMA = """
CREATE TABLE organizations (
    org_id TEXT PRIMARY KEY,
    org_name TEXT NOT NULL,
    org_type TEXT CHECK (org_type IN ('store', 'factory', 'warehouse')),
    owner_user_id TEXT NOT NULL,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
""".strip()


def get_organization_type_constraints() -> OrganizationTypeConstraintSystem:
    return OrganizationTypeConstraintSystem()


def get_organization_api_design() -> OrganizationApiDesign:
    return OrganizationApiDesign()


def get_organization_data_isolation_design() -> OrganizationDataIsolationDesign:
    return OrganizationDataIsolationDesign()


def get_organization_security_boundary() -> OrganizationSecurityBoundary:
    return OrganizationSecurityBoundary()


def get_organization_core_schema_completion_status() -> (
    OrganizationCoreSchemaCompletionStatus
):
    return OrganizationCoreSchemaCompletionStatus()
