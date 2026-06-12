export type ExecutionProviderType =
  | "no_op_provider"
  | "mock_provider"
  | "contract_only_provider"
  | "local_backend_provider"
  | "queue_provider"
  | "webhook_provider"
  | "scheduled_provider"
  | "future_live_provider";

export type ExecutionProviderStatus =
  | "draft"
  | "contract_ready"
  | "test_ready"
  | "provider_pending"
  | "provider_unavailable"
  | "disabled"
  | "deprecated"
  | "sealed";

export type ExecutionProviderLifecycle = ExecutionProviderStatus;

export type ExecutionMode =
  | "contract_only"
  | "no_op"
  | "mock"
  | "local_backend"
  | "queue"
  | "webhook"
  | "scheduled"
  | "future_live";

export type ExecutionActionType =
  | "read"
  | "manage"
  | "run"
  | "sync"
  | "generate"
  | "review"
  | "export"
  | "publish"
  | "prepare"
  | "declare"
  | "test_run";

export type ExecutionRiskLevel = "low" | "medium" | "high" | "critical";

export type ExecutionApprovalStatus =
  | "not_required"
  | "blocked_approval_required"
  | "waiting_c12";

export type ExecutionSecretBindingStatus =
  | "not_required"
  | "declared_only"
  | "secret_rules_required"
  | "waiting_c14";

export type ExecutionScopeStatus =
  | "not_required"
  | "adapter_pending"
  | "scope_adapter_pending"
  | "waiting_c18";

export type ExecutionProviderAccessStateName =
  | "visible"
  | "hidden"
  | "locked"
  | "unavailable"
  | "blocked"
  | "provider_pending"
  | "disabled"
  | "deprecated";

export type ExecutionApprovalRequirement = {
  requires_approval: boolean;
  approval_status: ExecutionApprovalStatus;
  approval_provider_state: "not_required" | "waiting_c12";
  blocks_execution_in_c09b: boolean;
  reason: string;
};

export type ExecutionSecretRequirement = {
  requires_secret: boolean;
  secret_binding_status: ExecutionSecretBindingStatus;
  secret_read_allowed: false;
  rules_provider_state: "not_required" | "waiting_c14";
  blocks_execution_in_c09b: boolean;
  reason: string;
};

export type ExecutionScopeRequirement = {
  requires_scope: boolean;
  scope_status: ExecutionScopeStatus;
  allowed_scope_types: string[];
  requires_c18_scope_adapter: boolean;
  blocks_execution_in_c09b: boolean;
  reason: string;
};

export type ExecutionPolicyDeclaration = {
  policy_key: string;
  description: string;
  c09b_behavior: string;
  enabled_in_c09b: false;
};

export type ExecutionOperationLogPolicy = {
  operation_log_action: string;
  write_policy: "declared_only";
  writes_operation_logs_in_c09b: false;
  details_projection: string[];
  redaction_policy: string;
};

export type ExecutionAuditEventPolicy = {
  event_refs: string[];
  write_policy: "declared_only";
  writes_audit_events_in_c09b: false;
};

export type ExecutionArtifactPolicy = {
  artifact_refs_allowed: boolean;
  writes_artifacts_in_c09b: false;
  local_path_allowed: false;
  external_reference_allowed: false;
  safe_reference_only: true;
};

export type ExecutionCallbackPolicy = {
  callback_supported: false;
  callback_connected_in_c09b: false;
  correlation_id_policy: string;
  external_endpoint_declared: false;
};

export type ExecutionFailurePolicy = {
  safe_error_code_required: boolean;
  safe_error_message_required: boolean;
  raw_provider_error_exposed: false;
  retry_requires_policy_match: boolean;
};

export type ExecutionFallbackBehavior = {
  permission_missing: string;
  approval_missing: string;
  secret_missing: string;
  scope_missing: string;
  provider_missing: string;
};

export type ExecutionUnavailableBehavior = {
  block_reason: string;
  safe_status_message: string;
  show_to_user: boolean;
};

export type ExecutionProviderTestContract = {
  test_key: string;
  description: string;
  required: boolean;
};

export type ExecutionProviderContract = {
  provider_key: string;
  provider_version: string;
  provider_type: ExecutionProviderType;
  provider_status: ExecutionProviderStatus;
  lifecycle: ExecutionProviderLifecycle;
  display_name: string;
  description: string;
  supported_execution_modes: ExecutionMode[];
  supported_action_types: ExecutionActionType[];
  module_key: string;
  adapter_key: string;
  action_key: string;
  required_permissions: string[];
  risk_level: ExecutionRiskLevel;
  approval_requirement: ExecutionApprovalRequirement;
  secret_requirement: ExecutionSecretRequirement;
  scope_requirement: ExecutionScopeRequirement;
  idempotency_policy: ExecutionPolicyDeclaration;
  retry_policy: ExecutionPolicyDeclaration;
  timeout_policy: ExecutionPolicyDeclaration;
  cancellation_policy: ExecutionPolicyDeclaration;
  operation_log_policy: ExecutionOperationLogPolicy;
  audit_event_policy: ExecutionAuditEventPolicy;
  artifact_policy: ExecutionArtifactPolicy;
  callback_policy: ExecutionCallbackPolicy;
  failure_policy: ExecutionFailurePolicy;
  fallback_behavior: ExecutionFallbackBehavior;
  unavailable_behavior: ExecutionUnavailableBehavior;
  test_contracts: ExecutionProviderTestContract[];
  docs_path: string;
  operation_log_action: string;
  requires_execution_provider: boolean;
  requires_approval: boolean;
  executable: false;
  can_request_execution: false;
  no_execute_reason: string;
  safe_status_message: string;
};

export type ExecutionProviderAccessState = {
  provider_key: string;
  provider_type: ExecutionProviderType;
  provider_status: ExecutionProviderStatus;
  provider_access_state: ExecutionProviderAccessStateName;
  module_key: string;
  adapter_key: string;
  action_key: string;
  visible: boolean;
  hidden: boolean;
  locked: boolean;
  unavailable: boolean;
  blocked: boolean;
  block_reason: string;
  required_permission: string;
  missing_permissions: string[];
  risk_level: ExecutionRiskLevel;
  requires_approval: boolean;
  approval_status: ExecutionApprovalStatus;
  requires_secret: boolean;
  secret_binding_status: ExecutionSecretBindingStatus;
  requires_scope: boolean;
  scope_status: ExecutionScopeStatus;
  execution_mode: ExecutionMode;
  can_request_execution: false;
  executable: false;
  no_execute_reason: string;
  operation_log_action: string;
  safe_status_message: string;
};

export type ExecutionProviderRegistryResponse = {
  items: ExecutionProviderContract[];
  count: number;
};

export type UserExecutionProvidersResponse = {
  user_id: number;
  role: string;
  is_owner_full_access: boolean;
  items: ExecutionProviderAccessState[];
  count: number;
};

export type ExecutionProviderActionState = {
  provider_key: string | null;
  state:
    | "hidden"
    | "locked"
    | "approval_required"
    | "secret_required"
    | "scope_required"
    | "provider_pending"
    | "provider_unavailable"
    | "execution_provider_required"
    | "no_execute";
  title: string;
  message: string;
  detail: string;
  button_label: string;
  disabled: true;
  executable: false;
  can_request_execution: false;
  no_execute_reason: string;
};

const PROVIDER_TYPES = new Set<ExecutionProviderType>([
  "no_op_provider",
  "mock_provider",
  "contract_only_provider",
  "local_backend_provider",
  "queue_provider",
  "webhook_provider",
  "scheduled_provider",
  "future_live_provider",
]);

const PROVIDER_STATUSES = new Set<ExecutionProviderStatus>([
  "draft",
  "contract_ready",
  "test_ready",
  "provider_pending",
  "provider_unavailable",
  "disabled",
  "deprecated",
  "sealed",
]);

const EXECUTION_MODES = new Set<ExecutionMode>([
  "contract_only",
  "no_op",
  "mock",
  "local_backend",
  "queue",
  "webhook",
  "scheduled",
  "future_live",
]);

const ACTION_TYPES = new Set<ExecutionActionType>([
  "read",
  "manage",
  "run",
  "sync",
  "generate",
  "review",
  "export",
  "publish",
  "prepare",
  "declare",
  "test_run",
]);

const RISK_LEVELS = new Set<ExecutionRiskLevel>([
  "low",
  "medium",
  "high",
  "critical",
]);

const APPROVAL_STATUSES = new Set<ExecutionApprovalStatus>([
  "not_required",
  "blocked_approval_required",
  "waiting_c12",
]);

const SECRET_BINDING_STATUSES = new Set<ExecutionSecretBindingStatus>([
  "not_required",
  "declared_only",
  "secret_rules_required",
  "waiting_c14",
]);

const SCOPE_STATUSES = new Set<ExecutionScopeStatus>([
  "not_required",
  "adapter_pending",
  "scope_adapter_pending",
  "waiting_c18",
]);

const ACCESS_STATES = new Set<ExecutionProviderAccessStateName>([
  "visible",
  "hidden",
  "locked",
  "unavailable",
  "blocked",
  "provider_pending",
  "disabled",
  "deprecated",
]);

const SENSITIVE_PUBLIC_VALUE_MARKERS = [
  "." + "env",
  "auth" + "orization",
  "bearer ",
  "cred" + "ential",
  "en" + "v=",
  "en" + "v:",
  "http://",
  "https://",
  "pass" + "word",
  "provider_" + "url",
  "sec" + "ret=",
  "sec" + "ret:",
  "tok" + "en=",
  "tok" + "en:",
  "ur" + "l=",
  "ur" + "l:",
  "webhook_" + "url",
  "://",
];

const STATUS_LABELS: Record<ExecutionProviderStatus, string> = {
  contract_ready: "Contract ready",
  deprecated: "Deprecated",
  disabled: "Disabled",
  draft: "Draft",
  provider_pending: "Provider pending",
  provider_unavailable: "Provider unavailable",
  sealed: "Sealed",
  test_ready: "Test ready",
};

const DEFAULT_POLICY: ExecutionPolicyDeclaration = {
  c09b_behavior: "declared_only",
  description: "Declared for future execution provider stages.",
  enabled_in_c09b: false,
  policy_key: "declared_only",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
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

export function containsSensitiveExecutionProviderValue(value: string) {
  const lowered = value.toLowerCase();
  return SENSITIVE_PUBLIC_VALUE_MARKERS.some((marker) =>
    lowered.includes(marker),
  );
}

function safeString(value: unknown, fallback = "") {
  const raw = stringValue(value, fallback).trim();
  if (!raw || containsSensitiveExecutionProviderValue(raw)) {
    return fallback;
  }
  return raw;
}

function safeStringArray(value: unknown) {
  return uniqueStrings(stringArray(value).map((entry) => safeString(entry))).filter(
    Boolean,
  );
}

function normalizeProviderType(value: unknown): ExecutionProviderType {
  return typeof value === "string" &&
    PROVIDER_TYPES.has(value as ExecutionProviderType)
    ? (value as ExecutionProviderType)
    : "contract_only_provider";
}

function normalizeProviderStatus(value: unknown): ExecutionProviderStatus {
  return typeof value === "string" &&
    PROVIDER_STATUSES.has(value as ExecutionProviderStatus)
    ? (value as ExecutionProviderStatus)
    : "provider_pending";
}

function normalizeExecutionMode(value: unknown): ExecutionMode | null {
  return typeof value === "string" && EXECUTION_MODES.has(value as ExecutionMode)
    ? (value as ExecutionMode)
    : null;
}

function normalizeExecutionModes(value: unknown) {
  const modes = Array.isArray(value)
    ? value
        .map(normalizeExecutionMode)
        .filter((mode): mode is ExecutionMode => mode !== null)
    : [];
  return modes.length > 0 ? modes : ["contract_only" as const];
}

function normalizeActionTypes(value: unknown) {
  return Array.isArray(value)
    ? value.filter(
        (entry): entry is ExecutionActionType =>
          typeof entry === "string" &&
          ACTION_TYPES.has(entry as ExecutionActionType),
      )
    : [];
}

function normalizeRiskLevel(value: unknown): ExecutionRiskLevel {
  return typeof value === "string" && RISK_LEVELS.has(value as ExecutionRiskLevel)
    ? (value as ExecutionRiskLevel)
    : "low";
}

function normalizeApprovalStatus(value: unknown): ExecutionApprovalStatus {
  return typeof value === "string" &&
    APPROVAL_STATUSES.has(value as ExecutionApprovalStatus)
    ? (value as ExecutionApprovalStatus)
    : "not_required";
}

function normalizeSecretBindingStatus(
  value: unknown,
): ExecutionSecretBindingStatus {
  return typeof value === "string" &&
    SECRET_BINDING_STATUSES.has(value as ExecutionSecretBindingStatus)
    ? (value as ExecutionSecretBindingStatus)
    : "not_required";
}

function normalizeScopeStatus(value: unknown): ExecutionScopeStatus {
  return typeof value === "string" &&
    SCOPE_STATUSES.has(value as ExecutionScopeStatus)
    ? (value as ExecutionScopeStatus)
    : "not_required";
}

function normalizeAccessState(
  value: unknown,
): ExecutionProviderAccessStateName {
  return typeof value === "string" &&
    ACCESS_STATES.has(value as ExecutionProviderAccessStateName)
    ? (value as ExecutionProviderAccessStateName)
    : "unavailable";
}

function normalizePolicy(value: unknown): ExecutionPolicyDeclaration {
  const record = isRecord(value) ? value : {};
  return {
    c09b_behavior: safeString(record.c09b_behavior, DEFAULT_POLICY.c09b_behavior),
    description: safeString(record.description, DEFAULT_POLICY.description),
    enabled_in_c09b: false,
    policy_key: safeString(record.policy_key, DEFAULT_POLICY.policy_key),
  };
}

function normalizeApprovalRequirement(
  value: unknown,
): ExecutionApprovalRequirement {
  const record = isRecord(value) ? value : {};
  const requiresApproval = booleanValue(record.requires_approval, false);
  return {
    approval_provider_state:
      record.approval_provider_state === "waiting_c12"
        ? "waiting_c12"
        : "not_required",
    approval_status: normalizeApprovalStatus(record.approval_status),
    blocks_execution_in_c09b: booleanValue(
      record.blocks_execution_in_c09b,
      requiresApproval,
    ),
    reason: safeString(
      record.reason,
      requiresApproval
        ? "waiting for C12 Approval Gate"
        : "Approval is not required.",
    ),
    requires_approval: requiresApproval,
  };
}

function normalizeSecretRequirement(
  value: unknown,
): ExecutionSecretRequirement {
  const record = isRecord(value) ? value : {};
  const requiresSecret = booleanValue(record.requires_secret, false);
  return {
    blocks_execution_in_c09b: booleanValue(
      record.blocks_execution_in_c09b,
      requiresSecret,
    ),
    reason: safeString(
      record.reason,
      requiresSecret
        ? "waiting for C14 Secret Rules"
        : "Secret Rules are not required.",
    ),
    requires_secret: requiresSecret,
    rules_provider_state:
      record.rules_provider_state === "waiting_c14"
        ? "waiting_c14"
        : "not_required",
    secret_binding_status: normalizeSecretBindingStatus(
      record.secret_binding_status,
    ),
    secret_read_allowed: false,
  };
}

function normalizeScopeRequirement(value: unknown): ExecutionScopeRequirement {
  const record = isRecord(value) ? value : {};
  const requiresScope = booleanValue(record.requires_scope, false);
  return {
    allowed_scope_types: safeStringArray(record.allowed_scope_types),
    blocks_execution_in_c09b: booleanValue(
      record.blocks_execution_in_c09b,
      requiresScope,
    ),
    reason: safeString(
      record.reason,
      requiresScope
        ? "waiting for C18 Scope Adapter"
        : "Scope adapter is not required.",
    ),
    requires_c18_scope_adapter: booleanValue(
      record.requires_c18_scope_adapter,
      requiresScope,
    ),
    requires_scope: requiresScope,
    scope_status: normalizeScopeStatus(record.scope_status),
  };
}

function normalizeOperationLogPolicy(
  value: unknown,
): ExecutionOperationLogPolicy {
  const record = isRecord(value) ? value : {};
  return {
    details_projection: safeStringArray(record.details_projection),
    operation_log_action: safeString(
      record.operation_log_action,
      "execution.declared_only",
    ),
    redaction_policy: safeString(record.redaction_policy, "safe_fields_only"),
    write_policy: "declared_only",
    writes_operation_logs_in_c09b: false,
  };
}

function normalizeAuditEventPolicy(value: unknown): ExecutionAuditEventPolicy {
  const record = isRecord(value) ? value : {};
  return {
    event_refs: safeStringArray(record.event_refs),
    write_policy: "declared_only",
    writes_audit_events_in_c09b: false,
  };
}

function normalizeArtifactPolicy(value: unknown): ExecutionArtifactPolicy {
  const record = isRecord(value) ? value : {};
  return {
    artifact_refs_allowed: booleanValue(record.artifact_refs_allowed, true),
    external_reference_allowed: false,
    local_path_allowed: false,
    safe_reference_only: true,
    writes_artifacts_in_c09b: false,
  };
}

function normalizeCallbackPolicy(value: unknown): ExecutionCallbackPolicy {
  const record = isRecord(value) ? value : {};
  return {
    callback_connected_in_c09b: false,
    callback_supported: false,
    correlation_id_policy: safeString(
      record.correlation_id_policy,
      "declared_only",
    ),
    external_endpoint_declared: false,
  };
}

function normalizeFailurePolicy(value: unknown): ExecutionFailurePolicy {
  const record = isRecord(value) ? value : {};
  return {
    raw_provider_error_exposed: false,
    retry_requires_policy_match: booleanValue(
      record.retry_requires_policy_match,
      true,
    ),
    safe_error_code_required: booleanValue(
      record.safe_error_code_required,
      true,
    ),
    safe_error_message_required: booleanValue(
      record.safe_error_message_required,
      true,
    ),
  };
}

function normalizeFallbackBehavior(value: unknown): ExecutionFallbackBehavior {
  const record = isRecord(value) ? value : {};
  return {
    approval_missing: safeString(
      record.approval_missing,
      "waiting for C12 Approval Gate",
    ),
    permission_missing: safeString(
      record.permission_missing,
      "Missing required permission.",
    ),
    provider_missing: safeString(
      record.provider_missing,
      "waiting for C09 Execution Provider",
    ),
    scope_missing: safeString(
      record.scope_missing,
      "waiting for C18 Scope Adapter",
    ),
    secret_missing: safeString(
      record.secret_missing,
      "waiting for C14 Secret Rules",
    ),
  };
}

function normalizeUnavailableBehavior(
  value: unknown,
): ExecutionUnavailableBehavior {
  const record = isRecord(value) ? value : {};
  return {
    block_reason: safeString(record.block_reason, "no_execute_c09c"),
    safe_status_message: safeString(
      record.safe_status_message,
      "Execution Provider contract is readable; execution is disabled.",
    ),
    show_to_user: booleanValue(record.show_to_user, true),
  };
}

function normalizeTestContract(value: unknown): ExecutionProviderTestContract | null {
  if (!isRecord(value)) {
    return null;
  }
  const testKey = safeString(value.test_key);
  if (!testKey) {
    return null;
  }
  return {
    description: safeString(value.description, "Execution provider contract test."),
    required: booleanValue(value.required, true),
    test_key: testKey,
  };
}

export function normalizeExecutionProviderContract(
  value: unknown,
): ExecutionProviderContract | null {
  if (!isRecord(value) || typeof value.provider_key !== "string") {
    return null;
  }

  const providerKey = safeString(value.provider_key);
  const moduleKey = safeString(value.module_key);
  const adapterKey = safeString(value.adapter_key);
  const actionKey = safeString(value.action_key);
  if (!providerKey || !moduleKey || !adapterKey || !actionKey) {
    return null;
  }

  const unavailableBehavior = normalizeUnavailableBehavior(
    value.unavailable_behavior,
  );

  return {
    action_key: actionKey,
    adapter_key: adapterKey,
    approval_requirement: normalizeApprovalRequirement(
      value.approval_requirement,
    ),
    artifact_policy: normalizeArtifactPolicy(value.artifact_policy),
    audit_event_policy: normalizeAuditEventPolicy(value.audit_event_policy),
    callback_policy: normalizeCallbackPolicy(value.callback_policy),
    can_request_execution: false,
    cancellation_policy: normalizePolicy(value.cancellation_policy),
    description: safeString(value.description, "Execution provider contract."),
    display_name: safeString(value.display_name, providerKey),
    docs_path: safeString(value.docs_path),
    executable: false,
    failure_policy: normalizeFailurePolicy(value.failure_policy),
    fallback_behavior: normalizeFallbackBehavior(value.fallback_behavior),
    idempotency_policy: normalizePolicy(value.idempotency_policy),
    lifecycle: normalizeProviderStatus(value.lifecycle),
    module_key: moduleKey,
    no_execute_reason: safeString(
      value.no_execute_reason,
      unavailableBehavior.block_reason || "c09c_no_execute",
    ),
    operation_log_action: safeString(value.operation_log_action),
    operation_log_policy: normalizeOperationLogPolicy(value.operation_log_policy),
    provider_key: providerKey,
    provider_status: normalizeProviderStatus(value.provider_status),
    provider_type: normalizeProviderType(value.provider_type),
    provider_version: safeString(value.provider_version, "0.0.0"),
    required_permissions: safeStringArray(value.required_permissions),
    requires_approval: booleanValue(value.requires_approval, false),
    requires_execution_provider: booleanValue(
      value.requires_execution_provider,
      false,
    ),
    retry_policy: normalizePolicy(value.retry_policy),
    risk_level: normalizeRiskLevel(value.risk_level),
    safe_status_message: safeString(
      value.safe_status_message,
      unavailableBehavior.safe_status_message,
    ),
    scope_requirement: normalizeScopeRequirement(value.scope_requirement),
    secret_requirement: normalizeSecretRequirement(value.secret_requirement),
    supported_action_types: normalizeActionTypes(value.supported_action_types),
    supported_execution_modes: normalizeExecutionModes(
      value.supported_execution_modes,
    ),
    test_contracts: Array.isArray(value.test_contracts)
      ? value.test_contracts
          .map(normalizeTestContract)
          .filter((contract): contract is ExecutionProviderTestContract => contract !== null)
      : [],
    timeout_policy: normalizePolicy(value.timeout_policy),
    unavailable_behavior: unavailableBehavior,
  };
}

export function normalizeExecutionProviderRegistryResponse(
  value: unknown,
): ExecutionProviderRegistryResponse {
  const record = isRecord(value) ? value : {};
  const items = Array.isArray(record.items)
    ? record.items
        .map(normalizeExecutionProviderContract)
        .filter(
          (item): item is ExecutionProviderContract => item !== null,
        )
    : [];

  return {
    count: numberValue(record.count, items.length),
    items,
  };
}

export function normalizeExecutionProviderAccessState(
  value: unknown,
): ExecutionProviderAccessState | null {
  if (!isRecord(value) || typeof value.provider_key !== "string") {
    return null;
  }

  const providerKey = safeString(value.provider_key);
  const moduleKey = safeString(value.module_key);
  const adapterKey = safeString(value.adapter_key);
  const actionKey = safeString(value.action_key);
  const requiredPermission = safeString(value.required_permission);
  if (!providerKey || !moduleKey || !adapterKey || !actionKey) {
    return null;
  }

  const accessState = normalizeAccessState(value.provider_access_state);

  return {
    action_key: actionKey,
    adapter_key: adapterKey,
    approval_status: normalizeApprovalStatus(value.approval_status),
    block_reason: safeString(value.block_reason, "no_execute_c09c"),
    blocked: booleanValue(value.blocked, true),
    can_request_execution: false,
    executable: false,
    execution_mode:
      normalizeExecutionMode(value.execution_mode) ?? "contract_only",
    hidden: booleanValue(value.hidden, accessState === "hidden"),
    locked: booleanValue(value.locked, accessState === "locked"),
    missing_permissions: safeStringArray(value.missing_permissions),
    module_key: moduleKey,
    no_execute_reason: safeString(
      value.no_execute_reason,
      "c09c_no_execution_endpoint",
    ),
    operation_log_action: safeString(value.operation_log_action),
    provider_access_state: accessState,
    provider_key: providerKey,
    provider_status: normalizeProviderStatus(value.provider_status),
    provider_type: normalizeProviderType(value.provider_type),
    required_permission: requiredPermission,
    requires_approval: booleanValue(value.requires_approval, false),
    requires_scope: booleanValue(value.requires_scope, false),
    requires_secret: booleanValue(value.requires_secret, false),
    risk_level: normalizeRiskLevel(value.risk_level),
    safe_status_message: safeString(
      value.safe_status_message,
      "Execution Provider contract is readable; execution is disabled.",
    ),
    scope_status: normalizeScopeStatus(value.scope_status),
    secret_binding_status: normalizeSecretBindingStatus(
      value.secret_binding_status,
    ),
    unavailable: booleanValue(
      value.unavailable,
      accessState === "unavailable" ||
        accessState === "provider_pending" ||
        accessState === "disabled" ||
        accessState === "deprecated",
    ),
    visible: booleanValue(value.visible, accessState !== "hidden"),
  };
}

export function normalizeUserExecutionProvidersResponse(
  value: unknown,
): UserExecutionProvidersResponse {
  const record = isRecord(value) ? value : {};
  const items = Array.isArray(record.items)
    ? record.items
        .map(normalizeExecutionProviderAccessState)
        .filter(
          (item): item is ExecutionProviderAccessState => item !== null,
        )
    : [];

  return {
    count: numberValue(record.count, items.length),
    is_owner_full_access: booleanValue(record.is_owner_full_access, false),
    items,
    role: safeString(record.role),
    user_id: numberValue(record.user_id),
  };
}

export function findExecutionProviderAccessStateForAction(
  args: {
    moduleKey: string;
    adapterKey: string;
    actionKey: string;
  },
  accessStates: readonly ExecutionProviderAccessState[] | null | undefined,
) {
  return (
    accessStates?.find(
      (state) =>
        state.module_key === args.moduleKey &&
        state.adapter_key === args.adapterKey &&
        state.action_key === args.actionKey,
    ) ?? null
  );
}

export function findExecutionProviderContractForAction(
  args: {
    moduleKey: string;
    adapterKey: string;
    actionKey: string;
  },
  providers: readonly ExecutionProviderContract[] | null | undefined,
) {
  return (
    providers?.find(
      (provider) =>
        provider.module_key === args.moduleKey &&
        provider.adapter_key === args.adapterKey &&
        provider.action_key === args.actionKey,
    ) ?? null
  );
}

export function isExecutionProviderExecutable(
  _state: ExecutionProviderAccessState | ExecutionProviderContract | null | undefined,
) {
  return false;
}

export function canRequestExecution(
  _state: ExecutionProviderAccessState | ExecutionProviderContract | null | undefined,
) {
  return false;
}

export function getExecutionProviderStatusLabel(
  status: ExecutionProviderStatus | "unknown" | null | undefined,
) {
  if (!status || status === "unknown") {
    return "Provider unavailable";
  }
  return STATUS_LABELS[status] ?? "Provider unavailable";
}

function hasMarker(
  state: ExecutionProviderAccessState | null | undefined,
  marker: string,
) {
  return Boolean(
    state?.block_reason.includes(marker) ||
      state?.no_execute_reason.includes(marker) ||
      state?.provider_access_state.includes(marker),
  );
}

export function getExecutionProviderActionState({
  accessState,
  requiresApproval = false,
  requiresExecutionProvider = false,
}: {
  accessState?: ExecutionProviderAccessState | null;
  requiresApproval?: boolean;
  requiresExecutionProvider?: boolean;
}): ExecutionProviderActionState {
  const providerKey = accessState?.provider_key ?? null;
  const baseDetail =
    accessState?.safe_status_message ||
    "Execution Provider status is unavailable; action execution is disabled.";

  if (accessState?.hidden) {
    return {
      button_label: "Provider unavailable",
      can_request_execution: false,
      detail: baseDetail,
      disabled: true,
      executable: false,
      message: "Execution provider metadata is hidden.",
      no_execute_reason: accessState.no_execute_reason || "hidden",
      provider_key: providerKey,
      state: "hidden",
      title: "Provider hidden",
    };
  }

  if (accessState?.locked) {
    return {
      button_label: "Provider unavailable",
      can_request_execution: false,
      detail: baseDetail,
      disabled: true,
      executable: false,
      message: "Execution provider is locked by missing permission.",
      no_execute_reason: accessState.no_execute_reason || "missing_permission",
      provider_key: providerKey,
      state: "locked",
      title: "Provider locked",
    };
  }

  if (
    requiresApproval ||
    accessState?.requires_approval ||
    hasMarker(accessState, "approval")
  ) {
    return {
      button_label: "Provider unavailable",
      can_request_execution: false,
      detail: baseDetail,
      disabled: true,
      executable: false,
      message: "waiting for C12 Approval Gate",
      no_execute_reason:
        accessState?.no_execute_reason || "waiting_c12_approval_gate",
      provider_key: providerKey,
      state: "approval_required",
      title: "blocked_approval_required",
    };
  }

  if (
    accessState?.requires_secret ||
    accessState?.secret_binding_status === "secret_rules_required" ||
    hasMarker(accessState, "secret")
  ) {
    return {
      button_label: "Provider unavailable",
      can_request_execution: false,
      detail: baseDetail,
      disabled: true,
      executable: false,
      message: "waiting for C14 Secret Rules",
      no_execute_reason:
        accessState?.no_execute_reason || "waiting_c14_secret_rules",
      provider_key: providerKey,
      state: "secret_required",
      title: "secret_rules_required",
    };
  }

  if (
    accessState?.requires_scope ||
    accessState?.scope_status === "scope_adapter_pending" ||
    hasMarker(accessState, "scope")
  ) {
    return {
      button_label: "Provider unavailable",
      can_request_execution: false,
      detail: baseDetail,
      disabled: true,
      executable: false,
      message: "waiting for C18 Scope Adapter",
      no_execute_reason:
        accessState?.no_execute_reason || "waiting_c18_scope_adapter",
      provider_key: providerKey,
      state: "scope_required",
      title: "scope_adapter_pending",
    };
  }

  if (
    !accessState ||
    accessState.provider_access_state === "provider_pending" ||
    accessState.provider_status === "provider_pending"
  ) {
    return {
      button_label: "Provider unavailable",
      can_request_execution: false,
      detail: baseDetail,
      disabled: true,
      executable: false,
      message: "waiting for C09 Execution Provider",
      no_execute_reason: accessState?.no_execute_reason || "provider_pending",
      provider_key: providerKey,
      state: "provider_pending",
      title: "provider_pending",
    };
  }

  if (
    accessState.unavailable ||
    accessState.provider_access_state === "unavailable" ||
    accessState.provider_status === "provider_unavailable" ||
    accessState.provider_access_state === "disabled" ||
    accessState.provider_access_state === "deprecated"
  ) {
    return {
      button_label: "Provider unavailable",
      can_request_execution: false,
      detail: baseDetail,
      disabled: true,
      executable: false,
      message: "execution provider required",
      no_execute_reason: accessState.no_execute_reason || "provider_unavailable",
      provider_key: providerKey,
      state: "provider_unavailable",
      title:
        accessState.provider_access_state === "disabled"
          ? "provider_disabled"
          : "provider_unavailable",
    };
  }

  if (requiresExecutionProvider || hasMarker(accessState, "execution_provider")) {
    return {
      button_label: "Provider unavailable",
      can_request_execution: false,
      detail: baseDetail,
      disabled: true,
      executable: false,
      message: "waiting for C09 Execution Provider",
      no_execute_reason:
        accessState.no_execute_reason ||
        "c09c_no_execute_provider_contract_only",
      provider_key: providerKey,
      state: "execution_provider_required",
      title: "execution provider required",
    };
  }

  return {
    button_label: "Provider unavailable",
    can_request_execution: false,
    detail: baseDetail,
    disabled: true,
    executable: false,
    message: "Execution Provider contract is readable; execution is disabled.",
    no_execute_reason:
      accessState.no_execute_reason || "c09c_no_execution_endpoint",
    provider_key: providerKey,
    state: "no_execute",
    title: "C09C no-execute",
  };
}
