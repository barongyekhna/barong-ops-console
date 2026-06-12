export type AdapterStatus =
  | "draft"
  | "adapter_pending"
  | "contract_ready"
  | "test_ready"
  | "staging_ready"
  | "production_ready"
  | "disabled"
  | "deprecated"
  | "sealed";

export type AdapterLifecycle = AdapterStatus;

export type AdapterSurface =
  | "navigation"
  | "dashboard_card"
  | "module_page"
  | "detail_page"
  | "action_panel"
  | "settings_panel"
  | "audit_log_view"
  | "status_widget"
  | "future_approval_panel";

export type AdapterAccessStateName =
  | "available"
  | "locked"
  | "hidden"
  | "unavailable"
  | "adapter_pending"
  | "disabled";

export type AdapterRiskLevel = "low" | "medium" | "high" | "critical";

export type AdapterDependencyName =
  | "n8n"
  | "woocommerce"
  | "minio"
  | "filebrowser"
  | "ai_provider"
  | "serp"
  | "wecom"
  | "google_sheets";

export type AdapterExecutionProviderState =
  | "not_required"
  | "required_not_implemented_c08b"
  | "adapter_pending"
  | "disabled";

export type AdapterBindingSummary = {
  binding_type: "page" | "navigation" | "route" | "api";
  key: string;
  module_key: string;
  label: string;
  surface: AdapterSurface | null;
  route: string | null;
  route_namespace: string | null;
  api_namespace: string | null;
  method: string | null;
  required_permission: string | null;
  status: AdapterStatus;
  unavailable_behavior: string | null;
  no_api: boolean;
};

export type AdapterCapability = {
  capability_key: string;
  module_key: string;
  display_name: string;
  description: string;
  required_permission: string | null;
  surfaces: AdapterSurface[];
};

export type AdapterAction = {
  action_key: string;
  module_key: string;
  capability_key: string;
  display_name: string;
  description: string;
  required_permission: string;
  risk_level: AdapterRiskLevel;
  requires_approval: boolean;
  requires_execution_provider: boolean;
  operation_log_action: string;
  executable_before_c09: false;
  status: AdapterStatus;
};

export type AdapterActionContract = {
  action_key: string;
  input_contract: string;
  output_contract: string;
  required_permission: string;
  risk_level: AdapterRiskLevel;
  requires_approval: boolean;
  requires_execution_provider: boolean;
  execution_requirement_ref: string | null;
  operation_log_action: string;
  audit_event_refs: string[];
  idempotency_policy: string;
  timeout_policy: string;
  fallback_behavior: string;
  executable_before_c09: false;
};

export type AdapterDataContractSummary = {
  contract_key: string;
  contract_version: string;
  module_key: string;
  object_type: string;
  read_boundary: string[];
  write_boundary: string[];
  owner_module: string;
};

export type AdapterInputContractSummary = {
  contract_key: string;
  action_key: string | null;
  required_fields: string[];
  optional_fields: string[];
  validation_rules: string[];
  sensitive_fields: string[];
  redaction_policy: string;
};

export type AdapterOutputContractSummary = {
  contract_key: string;
  action_key: string | null;
  safe_summary_fields: string[];
  sensitive_fields: string[];
  redaction_policy: string;
  operation_log_projection: string[];
};

export type AdapterDependencyDeclaration = {
  dependency_key: AdapterDependencyName;
  dependency_type: string;
  required: boolean;
  provider_status: string;
  live_connection_allowed: false;
  safe_unavailable_message: string;
};

export type AdapterExecutionRequirement = {
  requires_execution_provider: boolean;
  executable_before_c09: false;
  execution_provider_state: AdapterExecutionProviderState;
  provider_contract_ref: string | null;
  queue_required: boolean;
  result_contract_ref: string | null;
};

export type AdapterApprovalRequirement = {
  requires_approval: boolean;
  high_risk_action_policy: string;
  approval_provider_state: "not_implemented_c08b";
  approval_reason_required: boolean;
};

export type ModuleAdapterContract = {
  adapter_key: string;
  adapter_version: string;
  module_key: string;
  manifest_version: string;
  display_name: string;
  description: string;
  adapter_status: AdapterStatus;
  lifecycle: AdapterLifecycle;
  supported_surfaces: AdapterSurface[];
  pages: AdapterBindingSummary[];
  nav_bindings: AdapterBindingSummary[];
  route_bindings: AdapterBindingSummary[];
  api_bindings: AdapterBindingSummary[];
  capabilities: AdapterCapability[];
  actions: AdapterAction[];
  action_contracts: AdapterActionContract[];
  data_contracts: AdapterDataContractSummary[];
  input_contracts: AdapterInputContractSummary[];
  output_contracts: AdapterOutputContractSummary[];
  dependency_declarations: AdapterDependencyDeclaration[];
  execution_requirements: AdapterExecutionRequirement;
  approval_requirements: AdapterApprovalRequirement;
  unavailable_behavior: string;
  docs_path: string;
};

export type ModuleAdapterAccessState = {
  adapter_key: string;
  module_key: string;
  visible: boolean;
  hidden: boolean;
  locked: boolean;
  unavailable: boolean;
  adapter_status: AdapterStatus;
  adapter_access_state: AdapterAccessStateName;
  supported_surfaces: AdapterSurface[];
  available_surfaces: AdapterSurface[];
  disabled_surfaces: AdapterSurface[];
  action_contracts: AdapterActionContract[];
  available_actions: string[];
  locked_actions: string[];
  unavailable_actions: string[];
  required_permissions: string[];
  missing_permissions: string[];
  requires_execution_provider: boolean;
  execution_provider_state: AdapterExecutionProviderState;
  requires_approval: boolean;
  reason: string;
};

export type ModuleAdapterRegistryResponse = {
  items: ModuleAdapterContract[];
  count: number;
};

export type UserModuleAdaptersResponse = {
  user_id: number;
  role: string;
  is_owner_full_access: boolean;
  items: ModuleAdapterAccessState[];
  count: number;
};

export type AdapterSurfaceState = {
  surface: AdapterSurface;
  declared: boolean;
  available: boolean;
  disabled: boolean;
  state:
    | "available"
    | "disabled"
    | "hidden"
    | "locked"
    | "unavailable"
    | "unknown";
  label: string;
  reason: string;
};

export type AdapterActionContractState = {
  action_key: string;
  executable: false;
  disabled: true;
  unavailable: true;
  requires_execution_provider: boolean;
  requires_approval: boolean;
  state:
    | "contract_only"
    | "execution_provider_required"
    | "approval_required"
    | "locked"
    | "unavailable";
  button_label: string;
  execution_message: string;
  approval_message: string | null;
  reason: string;
};

const ADAPTER_STATUSES = new Set<AdapterStatus>([
  "draft",
  "adapter_pending",
  "contract_ready",
  "test_ready",
  "staging_ready",
  "production_ready",
  "disabled",
  "deprecated",
  "sealed",
]);

const ADAPTER_SURFACES = new Set<AdapterSurface>([
  "navigation",
  "dashboard_card",
  "module_page",
  "detail_page",
  "action_panel",
  "settings_panel",
  "audit_log_view",
  "status_widget",
  "future_approval_panel",
]);

const ADAPTER_ACCESS_STATES = new Set<AdapterAccessStateName>([
  "available",
  "locked",
  "hidden",
  "unavailable",
  "adapter_pending",
  "disabled",
]);

const ADAPTER_RISK_LEVELS = new Set<AdapterRiskLevel>([
  "low",
  "medium",
  "high",
  "critical",
]);

const ADAPTER_EXECUTION_PROVIDER_STATES = new Set<AdapterExecutionProviderState>([
  "not_required",
  "required_not_implemented_c08b",
  "adapter_pending",
  "disabled",
]);

const SAFE_DEPENDENCY_NAMES = new Set<AdapterDependencyName>([
  "n8n",
  "woocommerce",
  "minio",
  "filebrowser",
  "ai_provider",
  "serp",
  "wecom",
  "google_sheets",
]);

const NON_EXECUTABLE_ADAPTER_STATUSES = new Set<AdapterStatus>([
  "draft",
  "adapter_pending",
  "disabled",
  "deprecated",
]);

const SENSITIVE_ADAPTER_MARKERS = [
  ".env",
  "authorization",
  "bearer ",
  "credential",
  "env",
  "http://",
  "https://",
  "password",
  "provider_url",
  "secret",
  "token",
  "url",
  "webhook",
  "://",
  "=",
];

const STATUS_LABELS: Record<AdapterStatus, string> = {
  adapter_pending: "Adapter pending",
  contract_ready: "Contract ready",
  deprecated: "Deprecated",
  disabled: "Disabled",
  draft: "Draft",
  production_ready: "Production ready",
  sealed: "Sealed",
  staging_ready: "Staging ready",
  test_ready: "Test ready",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function booleanValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function numberValue(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : fallback;
}

function stringArray(value: unknown) {
  return Array.isArray(value)
    ? value.filter((entry): entry is string => typeof entry === "string")
    : [];
}

function uniqueStrings(values: readonly string[]) {
  return Array.from(new Set(values.filter(Boolean)));
}

function containsSensitiveMarker(value: string) {
  const lowered = value.toLowerCase();
  return SENSITIVE_ADAPTER_MARKERS.some((marker) => lowered.includes(marker));
}

function safeString(value: unknown, fallback = "") {
  const raw = stringValue(value, fallback).trim();
  if (!raw || containsSensitiveMarker(raw)) {
    return fallback;
  }
  return raw;
}

function safeStringArray(value: unknown) {
  return uniqueStrings(stringArray(value).map((entry) => safeString(entry))).filter(
    Boolean,
  );
}

function normalizeAdapterStatus(value: unknown): AdapterStatus {
  return typeof value === "string" && ADAPTER_STATUSES.has(value as AdapterStatus)
    ? (value as AdapterStatus)
    : "adapter_pending";
}

function normalizeAdapterSurface(value: unknown): AdapterSurface | null {
  return typeof value === "string" && ADAPTER_SURFACES.has(value as AdapterSurface)
    ? (value as AdapterSurface)
    : null;
}

function normalizeAdapterSurfaces(value: unknown) {
  return Array.isArray(value)
    ? value
        .map(normalizeAdapterSurface)
        .filter((surface): surface is AdapterSurface => surface !== null)
    : [];
}

function normalizeAdapterAccessStateName(
  value: unknown,
): AdapterAccessStateName {
  return typeof value === "string" &&
    ADAPTER_ACCESS_STATES.has(value as AdapterAccessStateName)
    ? (value as AdapterAccessStateName)
    : "unavailable";
}

function normalizeRiskLevel(value: unknown): AdapterRiskLevel {
  return typeof value === "string" &&
    ADAPTER_RISK_LEVELS.has(value as AdapterRiskLevel)
    ? (value as AdapterRiskLevel)
    : "low";
}

function normalizeExecutionProviderState(
  value: unknown,
): AdapterExecutionProviderState {
  return typeof value === "string" &&
    ADAPTER_EXECUTION_PROVIDER_STATES.has(
      value as AdapterExecutionProviderState,
    )
    ? (value as AdapterExecutionProviderState)
    : "required_not_implemented_c08b";
}

function normalizeBindingSummary(
  value: unknown,
  bindingType: AdapterBindingSummary["binding_type"],
): AdapterBindingSummary | null {
  if (!isRecord(value)) {
    return null;
  }

  const key =
    bindingType === "page"
      ? safeString(value.page_key)
      : bindingType === "navigation"
        ? safeString(value.nav_key)
        : bindingType === "route"
          ? safeString(value.route_key)
          : safeString(value.api_key);
  const moduleKey = safeString(value.module_key);

  if (!key || !moduleKey) {
    return null;
  }

  return {
    api_namespace:
      bindingType === "api" ? safeString(value.api_namespace, "no_api") : null,
    binding_type: bindingType,
    key,
    label:
      bindingType === "navigation"
        ? safeString(value.label, key)
        : safeString(value.display_name, key),
    method: bindingType === "api" ? safeString(value.method, "NO_API") : null,
    module_key: moduleKey,
    no_api: booleanValue(value.no_api, false),
    required_permission: optionalString(value.required_permission),
    route:
      bindingType === "api"
        ? safeString(value.path, "no_api")
        : safeString(value.route ?? value.path),
    route_namespace: safeString(value.route_namespace) || null,
    status: normalizeAdapterStatus(value.status),
    surface: normalizeAdapterSurface(value.surface),
    unavailable_behavior: optionalString(value.unavailable_behavior),
  };
}

function normalizeCapability(value: unknown): AdapterCapability | null {
  if (!isRecord(value)) {
    return null;
  }
  const capabilityKey = safeString(value.capability_key);
  const moduleKey = safeString(value.module_key);
  if (!capabilityKey || !moduleKey) {
    return null;
  }

  return {
    capability_key: capabilityKey,
    description: safeString(value.description),
    display_name: safeString(value.display_name, capabilityKey),
    module_key: moduleKey,
    required_permission: optionalString(value.required_permission),
    surfaces: normalizeAdapterSurfaces(value.surfaces),
  };
}

function normalizeAction(value: unknown): AdapterAction | null {
  if (!isRecord(value)) {
    return null;
  }
  const actionKey = safeString(value.action_key);
  const moduleKey = safeString(value.module_key);
  const capabilityKey = safeString(value.capability_key);
  const requiredPermission = safeString(value.required_permission);
  if (!actionKey || !moduleKey || !capabilityKey || !requiredPermission) {
    return null;
  }

  return {
    action_key: actionKey,
    capability_key: capabilityKey,
    description: safeString(value.description),
    display_name: safeString(value.display_name, actionKey),
    executable_before_c09: false,
    module_key: moduleKey,
    operation_log_action: safeString(value.operation_log_action),
    required_permission: requiredPermission,
    requires_approval: booleanValue(value.requires_approval, false),
    requires_execution_provider: booleanValue(
      value.requires_execution_provider,
      false,
    ),
    risk_level: normalizeRiskLevel(value.risk_level),
    status: normalizeAdapterStatus(value.status),
  };
}

function normalizeActionContract(value: unknown): AdapterActionContract | null {
  if (!isRecord(value)) {
    return null;
  }
  const actionKey = safeString(value.action_key);
  const inputContract = safeString(value.input_contract);
  const outputContract = safeString(value.output_contract);
  const requiredPermission = safeString(value.required_permission);
  if (!actionKey || !inputContract || !outputContract || !requiredPermission) {
    return null;
  }

  return {
    action_key: actionKey,
    audit_event_refs: safeStringArray(value.audit_event_refs),
    executable_before_c09: false,
    execution_requirement_ref: optionalString(value.execution_requirement_ref),
    fallback_behavior: safeString(value.fallback_behavior, "unavailable_before_c09"),
    idempotency_policy: safeString(value.idempotency_policy, "declared_only"),
    input_contract: inputContract,
    operation_log_action: safeString(value.operation_log_action),
    output_contract: outputContract,
    required_permission: requiredPermission,
    requires_approval: booleanValue(value.requires_approval, false),
    requires_execution_provider: booleanValue(
      value.requires_execution_provider,
      false,
    ),
    risk_level: normalizeRiskLevel(value.risk_level),
    timeout_policy: safeString(value.timeout_policy, "declared_only"),
  };
}

function normalizeDataContract(value: unknown): AdapterDataContractSummary | null {
  if (!isRecord(value)) {
    return null;
  }
  const contractKey = safeString(value.contract_key);
  const moduleKey = safeString(value.module_key);
  if (!contractKey || !moduleKey) {
    return null;
  }

  return {
    contract_key: contractKey,
    contract_version: safeString(value.contract_version, "1.0.0"),
    module_key: moduleKey,
    object_type: safeString(value.object_type),
    owner_module: safeString(value.owner_module, moduleKey),
    read_boundary: safeStringArray(value.read_boundary),
    write_boundary: safeStringArray(value.write_boundary),
  };
}

function normalizeInputContract(
  value: unknown,
): AdapterInputContractSummary | null {
  if (!isRecord(value)) {
    return null;
  }
  const contractKey = safeString(value.contract_key);
  if (!contractKey) {
    return null;
  }

  return {
    action_key: optionalString(value.action_key),
    contract_key: contractKey,
    optional_fields: safeStringArray(value.optional_fields),
    redaction_policy: safeString(value.redaction_policy, "safe_fields_only"),
    required_fields: safeStringArray(value.required_fields),
    sensitive_fields: [],
    validation_rules: safeStringArray(value.validation_rules),
  };
}

function normalizeOutputContract(
  value: unknown,
): AdapterOutputContractSummary | null {
  if (!isRecord(value)) {
    return null;
  }
  const contractKey = safeString(value.contract_key);
  if (!contractKey) {
    return null;
  }

  return {
    action_key: optionalString(value.action_key),
    contract_key: contractKey,
    operation_log_projection: safeStringArray(value.operation_log_projection),
    redaction_policy: safeString(value.redaction_policy, "safe_fields_only"),
    safe_summary_fields: safeStringArray(value.safe_summary_fields),
    sensitive_fields: [],
  };
}

function normalizeDependency(
  value: unknown,
): AdapterDependencyDeclaration | null {
  if (!isRecord(value) || typeof value.dependency_key !== "string") {
    return null;
  }
  const dependencyKey = value.dependency_key.trim().toLowerCase();
  if (
    !SAFE_DEPENDENCY_NAMES.has(dependencyKey as AdapterDependencyName) ||
    containsSensitiveMarker(dependencyKey)
  ) {
    return null;
  }

  return {
    dependency_key: dependencyKey as AdapterDependencyName,
    dependency_type: safeString(value.dependency_type, "declared"),
    live_connection_allowed: false,
    provider_status: safeString(value.provider_status, "declared_only"),
    required: booleanValue(value.required, false),
    safe_unavailable_message: safeString(
      value.safe_unavailable_message,
      "Dependency declared only.",
    ),
  };
}

function normalizeExecutionRequirement(
  value: unknown,
): AdapterExecutionRequirement {
  const record = isRecord(value) ? value : {};
  return {
    executable_before_c09: false,
    execution_provider_state: normalizeExecutionProviderState(
      record.execution_provider_state,
    ),
    provider_contract_ref: optionalString(record.provider_contract_ref),
    queue_required: booleanValue(record.queue_required, false),
    requires_execution_provider: booleanValue(
      record.requires_execution_provider,
      false,
    ),
    result_contract_ref: optionalString(record.result_contract_ref),
  };
}

function normalizeApprovalRequirement(value: unknown): AdapterApprovalRequirement {
  const record = isRecord(value) ? value : {};
  return {
    approval_provider_state: "not_implemented_c08b",
    approval_reason_required: booleanValue(
      record.approval_reason_required,
      false,
    ),
    high_risk_action_policy: safeString(
      record.high_risk_action_policy,
      "not_required",
    ),
    requires_approval: booleanValue(record.requires_approval, false),
  };
}

export function normalizeAdapterContract(
  value: unknown,
): ModuleAdapterContract | null {
  if (!isRecord(value) || typeof value.adapter_key !== "string") {
    return null;
  }

  const adapterKey = safeString(value.adapter_key);
  const moduleKey = safeString(value.module_key);
  if (!adapterKey || !moduleKey) {
    return null;
  }

  return {
    action_contracts: Array.isArray(value.action_contracts)
      ? value.action_contracts
          .map(normalizeActionContract)
          .filter(
            (
              contract,
            ): contract is AdapterActionContract => contract !== null,
          )
      : [],
    actions: Array.isArray(value.actions)
      ? value.actions
          .map(normalizeAction)
          .filter((action): action is AdapterAction => action !== null)
      : [],
    adapter_key: adapterKey,
    adapter_status: normalizeAdapterStatus(value.adapter_status),
    adapter_version: safeString(value.adapter_version, "0.0.0"),
    api_bindings: Array.isArray(value.api_bindings)
      ? value.api_bindings
          .map((entry) => normalizeBindingSummary(entry, "api"))
          .filter((entry): entry is AdapterBindingSummary => entry !== null)
      : [],
    approval_requirements: normalizeApprovalRequirement(
      value.approval_requirements,
    ),
    capabilities: Array.isArray(value.capabilities)
      ? value.capabilities
          .map(normalizeCapability)
          .filter(
            (capability): capability is AdapterCapability =>
              capability !== null,
          )
      : [],
    data_contracts: Array.isArray(value.data_contracts)
      ? value.data_contracts
          .map(normalizeDataContract)
          .filter(
            (
              contract,
            ): contract is AdapterDataContractSummary => contract !== null,
          )
      : [],
    dependency_declarations: Array.isArray(value.dependency_declarations)
      ? value.dependency_declarations
          .map(normalizeDependency)
          .filter(
            (
              dependency,
            ): dependency is AdapterDependencyDeclaration =>
              dependency !== null,
          )
      : [],
    description: safeString(value.description),
    display_name: safeString(value.display_name, adapterKey),
    docs_path: safeString(value.docs_path),
    execution_requirements: normalizeExecutionRequirement(
      value.execution_requirements,
    ),
    input_contracts: Array.isArray(value.input_contracts)
      ? value.input_contracts
          .map(normalizeInputContract)
          .filter(
            (
              contract,
            ): contract is AdapterInputContractSummary => contract !== null,
          )
      : [],
    lifecycle: normalizeAdapterStatus(value.lifecycle),
    manifest_version: safeString(value.manifest_version, "v1"),
    module_key: moduleKey,
    nav_bindings: Array.isArray(value.nav_bindings)
      ? value.nav_bindings
          .map((entry) => normalizeBindingSummary(entry, "navigation"))
          .filter((entry): entry is AdapterBindingSummary => entry !== null)
      : [],
    output_contracts: Array.isArray(value.output_contracts)
      ? value.output_contracts
          .map(normalizeOutputContract)
          .filter(
            (
              contract,
            ): contract is AdapterOutputContractSummary => contract !== null,
          )
      : [],
    pages: Array.isArray(value.pages)
      ? value.pages
          .map((entry) => normalizeBindingSummary(entry, "page"))
          .filter((entry): entry is AdapterBindingSummary => entry !== null)
      : [],
    route_bindings: Array.isArray(value.route_bindings)
      ? value.route_bindings
          .map((entry) => normalizeBindingSummary(entry, "route"))
          .filter((entry): entry is AdapterBindingSummary => entry !== null)
      : [],
    supported_surfaces: normalizeAdapterSurfaces(value.supported_surfaces),
    unavailable_behavior: safeString(value.unavailable_behavior, "show_unavailable"),
  };
}

export function normalizeModuleAdapterRegistryResponse(
  value: unknown,
): ModuleAdapterRegistryResponse {
  const record = isRecord(value) ? value : {};
  const items = Array.isArray(record.items)
    ? record.items
        .map(normalizeAdapterContract)
        .filter((item): item is ModuleAdapterContract => item !== null)
    : [];

  return {
    count: numberValue(record.count, items.length),
    items,
  };
}

export function normalizeAdapterAccessState(
  value: unknown,
): ModuleAdapterAccessState | null {
  if (!isRecord(value) || typeof value.adapter_key !== "string") {
    return null;
  }

  const adapterKey = safeString(value.adapter_key);
  const moduleKey = safeString(value.module_key);
  if (!adapterKey || !moduleKey) {
    return null;
  }

  const rawAvailableActions = safeStringArray(value.available_actions);
  const accessState = normalizeAdapterAccessStateName(value.adapter_access_state);
  const adapterStatus = normalizeAdapterStatus(value.adapter_status);

  return {
    action_contracts: Array.isArray(value.action_contracts)
      ? value.action_contracts
          .map(normalizeActionContract)
          .filter(
            (
              contract,
            ): contract is AdapterActionContract => contract !== null,
          )
      : [],
    adapter_access_state: accessState,
    adapter_key: adapterKey,
    adapter_status: adapterStatus,
    available_actions: [],
    available_surfaces: normalizeAdapterSurfaces(value.available_surfaces).filter(
      (surface) => surface !== "action_panel",
    ),
    disabled_surfaces: normalizeAdapterSurfaces(value.disabled_surfaces),
    execution_provider_state: normalizeExecutionProviderState(
      value.execution_provider_state,
    ),
    hidden: booleanValue(value.hidden, accessState === "hidden"),
    locked: booleanValue(value.locked, accessState === "locked"),
    missing_permissions: safeStringArray(value.missing_permissions),
    module_key: moduleKey,
    reason: safeString(value.reason),
    required_permissions: safeStringArray(value.required_permissions),
    requires_approval: booleanValue(value.requires_approval, false),
    requires_execution_provider: booleanValue(
      value.requires_execution_provider,
      false,
    ),
    supported_surfaces: normalizeAdapterSurfaces(value.supported_surfaces),
    unavailable: booleanValue(
      value.unavailable,
      accessState === "adapter_pending" ||
        accessState === "disabled" ||
        accessState === "unavailable" ||
        NON_EXECUTABLE_ADAPTER_STATUSES.has(adapterStatus),
    ),
    unavailable_actions: uniqueStrings([
      ...safeStringArray(value.unavailable_actions),
      ...rawAvailableActions,
    ]),
    visible: booleanValue(value.visible, false),
    locked_actions: safeStringArray(value.locked_actions),
  };
}

export function normalizeUserModuleAdaptersResponse(
  value: unknown,
): UserModuleAdaptersResponse {
  const record = isRecord(value) ? value : {};
  const items = Array.isArray(record.items)
    ? record.items
        .map(normalizeAdapterAccessState)
        .filter((item): item is ModuleAdapterAccessState => item !== null)
    : [];

  return {
    count: numberValue(record.count, items.length),
    is_owner_full_access: booleanValue(record.is_owner_full_access, false),
    items,
    role: safeString(record.role),
    user_id: numberValue(record.user_id),
  };
}

export function findAdapterAccessState(
  adapterKey: string,
  accessStates: readonly ModuleAdapterAccessState[] | null | undefined,
) {
  return (
    accessStates?.find((state) => state.adapter_key === adapterKey) ?? null
  );
}

export function findAdapterContract(
  adapterKey: string,
  adapters: readonly ModuleAdapterContract[] | null | undefined,
) {
  return adapters?.find((adapter) => adapter.adapter_key === adapterKey) ?? null;
}

export function findAdapterContractByModuleKey(
  moduleKey: string,
  adapters: readonly ModuleAdapterContract[] | null | undefined,
) {
  return adapters?.find((adapter) => adapter.module_key === moduleKey) ?? null;
}

export function isAdapterVisible(
  state: ModuleAdapterAccessState | null | undefined,
) {
  return Boolean(state?.visible && !state.hidden);
}

export function isAdapterHidden(
  state: ModuleAdapterAccessState | null | undefined,
) {
  return state ? state.hidden : true;
}

export function isAdapterLocked(
  state: ModuleAdapterAccessState | null | undefined,
) {
  return Boolean(state?.locked);
}

export function isAdapterUnavailable(
  state: ModuleAdapterAccessState | null | undefined,
) {
  if (!state) {
    return true;
  }
  return (
    state.unavailable ||
    state.adapter_access_state === "adapter_pending" ||
    state.adapter_access_state === "disabled" ||
    state.adapter_access_state === "unavailable" ||
    NON_EXECUTABLE_ADAPTER_STATUSES.has(state.adapter_status)
  );
}

export function isAdapterExecutable(
  _state: ModuleAdapterAccessState | null | undefined,
) {
  return false;
}

export function getAdapterStatusLabel(
  status: AdapterStatus | "unknown" | null | undefined,
) {
  if (!status || status === "unknown") {
    return "Adapter access unknown";
  }
  return STATUS_LABELS[status] ?? "Adapter access unknown";
}

export function getAdapterSurfaceState(
  adapter: ModuleAdapterContract | null | undefined,
  accessState: ModuleAdapterAccessState | null | undefined,
  surface: AdapterSurface,
): AdapterSurfaceState {
  const declared = Boolean(adapter?.supported_surfaces.includes(surface));

  if (!adapter || !accessState) {
    return {
      available: false,
      declared,
      disabled: true,
      label: "Adapter access unknown",
      reason: "Adapter metadata or access state is unavailable.",
      state: "unknown",
      surface,
    };
  }

  if (!declared) {
    return {
      available: false,
      declared: false,
      disabled: true,
      label: "Not declared",
      reason: "This surface is not declared by the adapter contract.",
      state: "unavailable",
      surface,
    };
  }

  if (accessState.hidden) {
    return {
      available: false,
      declared,
      disabled: true,
      label: "Hidden",
      reason: "Adapter metadata is hidden by C07 module access.",
      state: "hidden",
      surface,
    };
  }

  if (accessState.locked) {
    return {
      available: false,
      declared,
      disabled: true,
      label: "Locked",
      reason: "Current user lacks the adapter permissions for this surface.",
      state: "locked",
      surface,
    };
  }

  if (isAdapterUnavailable(accessState)) {
    return {
      available: false,
      declared,
      disabled: true,
      label: "Unavailable",
      reason:
        accessState.reason ||
        "This adapter is pending, disabled, or unavailable.",
      state: "unavailable",
      surface,
    };
  }

  if (
    surface === "action_panel" ||
    accessState.disabled_surfaces.includes(surface) ||
    !accessState.available_surfaces.includes(surface)
  ) {
    return {
      available: false,
      declared,
      disabled: true,
      label:
        surface === "action_panel"
          ? "Execution Provider not connected"
          : "Disabled",
      reason:
        surface === "action_panel"
          ? "Action surfaces remain disabled until C09 Execution Provider is connected."
          : "This adapter surface is declared but disabled.",
      state: "disabled",
      surface,
    };
  }

  return {
    available: true,
    declared,
    disabled: false,
    label: "Available",
    reason: "Adapter contract metadata is available for this surface.",
    state: "available",
    surface,
  };
}

export function getActionContractState(
  contract: AdapterActionContract,
  accessState?: ModuleAdapterAccessState | null,
): AdapterActionContractState {
  const locked = accessState?.locked === true;
  const unavailable = !accessState || isAdapterUnavailable(accessState);
  const requiresExecution =
    contract.requires_execution_provider ||
    accessState?.requires_execution_provider === true;
  const requiresApproval =
    contract.requires_approval || accessState?.requires_approval === true;
  const state = locked
    ? "locked"
    : requiresApproval
      ? "approval_required"
      : requiresExecution
        ? "execution_provider_required"
        : unavailable
          ? "unavailable"
          : "contract_only";

  return {
    action_key: contract.action_key,
    approval_message: requiresApproval ? "等待 C12 Approval Gate" : null,
    button_label: "Execution Provider not connected",
    disabled: true,
    executable: false,
    execution_message: requiresExecution
      ? "等待 C09 Execution Provider"
      : "This action is declared by the module adapter but cannot run until C09 Execution Provider is connected.",
    reason: locked
      ? "Current user lacks the required adapter permission."
      : "This action is declared by the module adapter but cannot run until C09 Execution Provider is connected.",
    requires_approval: requiresApproval,
    requires_execution_provider: requiresExecution,
    state,
    unavailable: true,
  };
}

export function isAdminOrSystemAdapter(
  adapter: Pick<ModuleAdapterContract, "module_key">,
) {
  return (
    adapter.module_key.startsWith("admin.") ||
    adapter.module_key.startsWith("system.")
  );
}

export function canExposeAdapterMetadata(
  adapter: ModuleAdapterContract | null | undefined,
  accessState: ModuleAdapterAccessState | null | undefined,
  options: {
    adapterAccessUnknown?: boolean;
    isOwnerFullAccess?: boolean;
  } = {},
) {
  if (!adapter) {
    return false;
  }
  if (accessState?.hidden) {
    return false;
  }
  if (
    (options.adapterAccessUnknown === true || !accessState) &&
    isAdminOrSystemAdapter(adapter) &&
    options.isOwnerFullAccess !== true
  ) {
    return false;
  }
  return true;
}

export function getSafeDependencyNames(
  dependencies: readonly AdapterDependencyDeclaration[] | null | undefined,
) {
  return uniqueStrings(
    (dependencies ?? []).map((dependency) => dependency.dependency_key),
  );
}

export function adapterContainsUnsafeDependencyValue(
  adapter: ModuleAdapterContract,
) {
  return JSON.stringify(adapter.dependency_declarations).match(
    /secret|token|password|authorization|credential|api[_-]?key|env|url|https?:|webhook/i,
  ) !== null;
}

export function isFutureExampleAdapterEnabled(adapter: ModuleAdapterContract) {
  const key = `${adapter.adapter_key} ${adapter.module_key}`.toLowerCase();
  const futureExample =
    /(^|\.)k01\b|product_knowledge|\bp0[1-8]\b|p_series|product_page_automation/.test(
      key,
    );
  return (
    futureExample &&
    !["adapter_pending", "disabled", "draft"].includes(adapter.adapter_status)
  );
}
