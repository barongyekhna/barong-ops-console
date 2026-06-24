from typing import Literal

from pydantic import BaseModel, Field

from .common import ApiErrorInfo


ModuleCategory = Literal[
    "core",
    "admin",
    "system",
    "business",
    "integration",
    "experimental",
]
ModuleStatus = Literal[
    "planned",
    "adapter_pending",
    "installed",
    "enabled",
    "active",
    "production_ready",
    "disabled",
    "unavailable",
    "deprecated",
    "sealed",
]
ModuleLifecycle = Literal[
    "proposal",
    "designed",
    "adapter_ready",
    "execution_ready",
    "sandbox_ready",
    "staging_pending",
    "staging_accepted",
    "production_pending",
    "production_released",
    "sealed",
]
ModuleDeniedBehavior = Literal["show_locked", "hide_when_denied"]
ModuleUnavailableBehavior = Literal[
    "hide",
    "show_unavailable",
    "planned",
    "adapter_pending",
    "execution_not_connected",
    "disabled",
]
ModuleAccessState = Literal[
    "available",
    "locked",
    "hidden",
    "unavailable",
    "planned",
    "adapter_pending",
]
OperationLogRequirement = Literal["none", "optional", "required"]


class ModuleNavigation(BaseModel):
    group: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    icon: str = Field(min_length=1, max_length=80)
    order: int = Field(ge=0)
    default_visible: bool = True
    owner_only: bool = False


class ModulePermissionManifestEntry(BaseModel):
    permission_key: str = Field(min_length=1, max_length=255)
    module_key: str = Field(min_length=1, max_length=128)
    category: ModuleCategory
    action: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    risk_level: Literal["low", "medium", "high", "critical"]
    menu_policy: ModuleDeniedBehavior
    default_scope_type: str = Field(default="global", min_length=1, max_length=80)
    allowed_scope_types: list[str] = Field(default_factory=list)
    high_risk_confirmation_required: bool = False
    operation_log_required: bool = False


class ModuleOperationLogPolicy(BaseModel):
    read: OperationLogRequirement = "optional"
    write: OperationLogRequirement = "required"
    approve: OperationLogRequirement = "required"
    release: OperationLogRequirement = "required"


class ModuleDataBoundary(BaseModel):
    reads: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    blocked_objects: list[str] = Field(default_factory=list)


class ModuleReleaseRequirements(BaseModel):
    local_verify: bool = True
    staging_acceptance: bool = False
    production_archive: bool = False
    required_checks: list[str] = Field(default_factory=list)


class ModuleManifestV1(BaseModel):
    module_key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    category: ModuleCategory
    status: ModuleStatus
    lifecycle: ModuleLifecycle
    route_namespace: str = Field(min_length=1, max_length=255)
    api_namespace: str = Field(min_length=1, max_length=255)
    no_api: bool = False
    navigation: ModuleNavigation
    required_permissions: list[str] = Field(default_factory=list)
    permission_manifest: list[ModulePermissionManifestEntry] = Field(
        default_factory=list
    )
    denied_behavior: ModuleDeniedBehavior
    unavailable_behavior: ModuleUnavailableBehavior
    external_dependencies: list[str] = Field(default_factory=list)
    execution_provider_required: bool
    module_adapter_required: bool
    sandbox_required: bool
    feature_flag_key: str | None = Field(default=None, max_length=128)
    audit_log_actions: list[str] = Field(default_factory=list)
    operation_log_policy: ModuleOperationLogPolicy
    allowed_scope_types: list[str] = Field(default_factory=list)
    data_boundary: ModuleDataBoundary
    release_requirements: ModuleReleaseRequirements
    staging_acceptance_required: bool
    production_release_required: bool
    docs_path: str = Field(min_length=1, max_length=255)


class ModuleManifestRead(ModuleManifestV1):
    pass


class ModuleRegistryResponse(BaseModel):
    items: list[ModuleManifestRead]
    count: int = Field(ge=0)
    degraded: bool = False
    source: str = "live"
    error: ApiErrorInfo | None = None


class ModuleAccessRead(BaseModel):
    module_key: str
    visible: bool
    locked: bool
    hidden: bool
    unavailable: bool
    executable: bool
    access_state: ModuleAccessState
    denied_behavior: ModuleDeniedBehavior
    reason: str
    required_permissions: list[str]
    missing_permissions: list[str]
    status: ModuleStatus
    category: ModuleCategory
    route_namespace: str


class ModuleAccessListResponse(BaseModel):
    user_id: int
    role: str
    is_owner_full_access: bool
    items: list[ModuleAccessRead]
    count: int = Field(ge=0)
    degraded: bool = False
    source: str = "live"
    error: ApiErrorInfo | None = None
