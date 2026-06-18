import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";
import {
  canRequestExecution,
  findExecutionProviderAccessStateForAction,
  findExecutionProviderContractForAction,
  getExecutionProviderActionState,
  isExecutionProviderExecutable,
  normalizeExecutionProviderAccessState,
  normalizeExecutionProviderContract,
  normalizeExecutionProviderRegistryResponse,
  normalizeUserExecutionProvidersResponse,
} from "../../frontend/src/lib/execution-provider.ts";
import {
  getActionContractState,
  normalizeAdapterAccessState,
  normalizeAdapterContract,
} from "../../frontend/src/lib/module-adapter.ts";

const baseActionContract = {
  action_key: "business.products.placeholder.prepare",
  audit_event_refs: [],
  executable_before_c09: false,
  execution_requirement_ref: "business.products.execution.v1",
  fallback_behavior: "unavailable_before_c09",
  idempotency_policy: "declared_only",
  input_contract: "business.products.placeholder.input.v1",
  operation_log_action: "business.products.placeholder.prepare",
  output_contract: "business.products.placeholder.output.v1",
  required_permission: "products.read",
  requires_approval: false,
  requires_execution_provider: true,
  risk_level: "medium",
  timeout_policy: "declared_only",
};

function provider(raw = {}) {
  const normalized = normalizeExecutionProviderContract({
    action_key: "business.products.placeholder.prepare",
    adapter_key: "business.products.placeholder.adapter",
    approval_requirement: {
      approval_provider_state: "not_required",
      approval_status: "not_required",
      blocks_execution_in_c09b: false,
      reason: "Approval is not required.",
      requires_approval: false,
    },
    artifact_policy: {
      artifact_refs_allowed: true,
      external_reference_allowed: true,
      local_path_allowed: true,
      safe_reference_only: true,
      writes_artifacts_in_c09b: true,
    },
    audit_event_policy: {
      event_refs: ["execution.declared"],
      write_policy: "declared_only",
      writes_audit_events_in_c09b: true,
    },
    callback_policy: {
      callback_connected_in_c09b: true,
      callback_supported: true,
      correlation_id_policy: "declared_only",
      external_endpoint_declared: true,
    },
    cancellation_policy: {
      c09b_behavior: "declared_only",
      description: "Cancellation is declared only.",
      enabled_in_c09b: true,
      policy_key: "cancel.policy",
    },
    description: "Products placeholder provider.",
    display_name: "Products Placeholder Provider",
    docs_path: "docs/C09_EXECUTION_PROVIDER_BACKEND.md",
    executable: true,
    failure_policy: {
      raw_provider_error_exposed: true,
      retry_requires_policy_match: true,
      safe_error_code_required: true,
      safe_error_message_required: true,
    },
    fallback_behavior: {
      approval_missing: "waiting for C12 Approval Gate",
      permission_missing: "Missing permission.",
      provider_missing: "waiting for C09 Execution Provider",
      scope_missing: "waiting for C18 Scope Adapter",
      secret_missing: "waiting for C14 Secret Rules",
    },
    idempotency_policy: {
      c09b_behavior: "declared_only",
      description: "Idempotency is declared only.",
      enabled_in_c09b: true,
      policy_key: "idempotency.policy",
    },
    lifecycle: "contract_ready",
    module_key: "business.products",
    operation_log_action: "business.products.placeholder.prepare",
    operation_log_policy: {
      details_projection: ["module_key", "adapter_key"],
      operation_log_action: "business.products.placeholder.prepare",
      redaction_policy: "safe_fields_only",
      write_policy: "declared_only",
      writes_operation_logs_in_c09b: true,
    },
    provider_key: "core.no_op_provider",
    provider_status: "contract_ready",
    provider_type: "no_op_provider",
    provider_version: "1.0.0",
    required_permissions: ["products.read"],
    requires_approval: false,
    requires_execution_provider: true,
    retry_policy: {
      c09b_behavior: "declared_only",
      description: "Retry is declared only.",
      enabled_in_c09b: true,
      policy_key: "retry.policy",
    },
    risk_level: "medium",
    scope_requirement: {
      allowed_scope_types: [],
      blocks_execution_in_c09b: false,
      reason: "Scope adapter is not required.",
      requires_c18_scope_adapter: false,
      requires_scope: false,
      scope_status: "not_required",
    },
    secret_requirement: {
      blocks_execution_in_c09b: false,
      provider_credential_declared: true,
      reason: "Secret Rules are not required.",
      requires_secret: false,
      rules_provider_state: "not_required",
      secret_binding_status: "not_required",
      secret_read_allowed: true,
      secret_value_declared: true,
    },
    supported_action_types: ["prepare"],
    supported_execution_modes: ["no_op"],
    test_contracts: [
      {
        description: "Validate C09C no-execute state.",
        required: true,
        test_key: "c09c.no_execute",
      },
    ],
    timeout_policy: {
      c09b_behavior: "declared_only",
      description: "Timeout is declared only.",
      enabled_in_c09b: true,
      policy_key: "timeout.policy",
    },
    unavailable_behavior: {
      block_reason: "no_execute_c09b",
      safe_status_message: "Execution Provider contract is readable.",
      show_to_user: true,
    },
    ...raw,
  });
  assert.notEqual(normalized, null);
  return normalized;
}

function access(raw = {}) {
  const normalized = normalizeExecutionProviderAccessState({
    action_key: "business.products.placeholder.prepare",
    adapter_key: "business.products.placeholder.adapter",
    approval_status: "not_required",
    block_reason: "execution_provider_required",
    blocked: true,
    can_request_execution: true,
    executable: true,
    execution_mode: "no_op",
    hidden: false,
    locked: false,
    missing_permissions: [],
    module_key: "business.products",
    no_execute_reason: "c09b_no_execute_provider_contract_only",
    operation_log_action: "business.products.placeholder.prepare",
    provider_access_state: "blocked",
    provider_key: "core.no_op_provider",
    provider_status: "contract_ready",
    provider_type: "no_op_provider",
    required_permission: "products.read",
    requires_approval: false,
    requires_scope: false,
    requires_secret: false,
    risk_level: "medium",
    safe_status_message:
      "Execution Provider contract is readable; execution is disabled.",
    scope_status: "not_required",
    secret_binding_status: "not_required",
    unavailable: false,
    visible: true,
    ...raw,
  });
  assert.notEqual(normalized, null);
  return normalized;
}

function adapterAccess(providerAccess = null, raw = {}) {
  const normalized = normalizeAdapterAccessState({
    action_contracts: [baseActionContract],
    adapter_access_state: "available",
    adapter_key: "business.products.placeholder.adapter",
    adapter_status: "contract_ready",
    available_actions: ["should.not.execute"],
    available_surfaces: ["navigation", "module_page", "status_widget"],
    disabled_surfaces: ["action_panel"],
    execution_provider_state: "required_not_implemented_c08b",
    hidden: false,
    locked: false,
    missing_permissions: [],
    module_key: "business.products",
    reason: "Adapter contract metadata is available.",
    required_permissions: ["products.read"],
    requires_approval: providerAccess?.requires_approval === true,
    requires_execution_provider: true,
    supported_surfaces: ["navigation", "module_page", "action_panel"],
    unavailable: false,
    unavailable_actions: [],
    visible: true,
    ...raw,
  });
  assert.notEqual(normalized, null);
  return normalized;
}

test("backend proxy precisely allows C09B execution provider registry paths", () => {
  assert.equal(
    isAllowedBackendProxyPath("GET", ["execution-providers", "registry"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["execution-providers", "me"]),
    true,
  );
});

test("backend proxy execution provider allowlist is exact GET-only matrix", () => {
  const allowedPaths = [
    ["execution-providers", "registry"],
    ["execution-providers", "me"],
  ];
  const deniedPaths = [
    ["execution-providers"],
    ["execution-providers", "registry", "extra"],
    ["execution-providers", "me", "extra"],
    ["execution-providers", "core.no_op_provider"],
    ["execution-providers", "core.no_op_provider", "run"],
    ["execution-providers", "execute"],
    ["execution-providers", "submit"],
    ["execution-providers", "cancel"],
    ["execution-providers", "retry"],
    ["executions"],
    ["executions", "run"],
    ["execution", "submit"],
  ];

  for (const path of allowedPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), true);
    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
      assert.equal(isAllowedBackendProxyPath(method, path), false);
    }
  }

  for (const path of deniedPaths) {
    for (const method of ["GET", "POST", "PUT", "PATCH", "DELETE"]) {
      assert.equal(isAllowedBackendProxyPath(method, path), false);
    }
  }
});

test("backend proxy rejects unsafe execution provider and execution paths", () => {
  assert.equal(
    isAllowedBackendProxyPath("POST", ["execution-providers", "registry"]),
    false,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["execution-providers", "not-allowed"]),
    false,
  );
  assert.equal(isAllowedBackendProxyPath("GET", ["executions"]), false);
  assert.equal(isAllowedBackendProxyPath("GET", ["executions", "run"]), false);
  assert.equal(
    isAllowedBackendProxyPath("POST", ["execution", "submit"]),
    false,
  );
});

test("execution provider API client is GET-only and uses exact safe paths", () => {
  const apiSource = readFileSync(
    "frontend/src/lib/execution-provider-api.ts",
    "utf8",
  );
  const proxySource = readFileSync(
    "frontend/src/app/api/backend/[...path]/route.ts",
    "utf8",
  );

  assert.match(apiSource, /getExecutionProviderRegistry/);
  assert.match(apiSource, /getMyExecutionProviders/);
  assert.match(apiSource, /apiRequest<unknown>\("\/execution-providers\/registry"/);
  assert.match(apiSource, /apiRequest<unknown>\("\/execution-providers\/me"/);
  assert.doesNotMatch(apiSource, /method:\s*["'](?:POST|PUT|PATCH|DELETE)["']/);
  assert.doesNotMatch(
    apiSource,
    /\/execution-providers\/[^"']*(?:actions?|execute|execution|run|submit|cancel|retry)/i,
  );
  assert.doesNotMatch(apiSource, /\/executions?\//i);
  assert.doesNotMatch(proxySource, /execution-providers\/\*/);
  assert.doesNotMatch(proxySource, /executions\/\*/);
  assert.match(proxySource, /ALLOWED_EXECUTION_PROVIDER_REGISTRY_PATHS/);
});

test("execution provider public model exposes C09B safe status fields only", () => {
  const source = readFileSync("frontend/src/lib/execution-provider.ts", "utf8");

  assert.match(source, /export type ExecutionProviderContract/);
  assert.match(source, /export type ExecutionProviderAccessState/);
  assert.match(source, /provider_key/);
  assert.match(source, /provider_status/);
  assert.match(source, /provider_access_state/);
  assert.match(source, /no_execute_reason/);
  assert.match(source, /safe_status_message/);
  assert.match(source, /can_request_execution: false/);
  assert.match(source, /executable: false/);
  assert.doesNotMatch(source, /password_value|token_value|provider_url|webhook_url/);
});

test("provider registry normalization forces no-execute and strips unsafe values", () => {
  const normalized = provider({
    description: "Authorization Bearer token=raw",
    display_name: "https://private.invalid/provider",
    docs_path: ".env.production",
    safe_status_message: "credential=raw",
    unavailable_behavior: {
      block_reason: "provider_pending",
      safe_status_message: "Provider is pending and cannot execute in C09C.",
      show_to_user: true,
    },
  });

  assert.equal(normalized.executable, false);
  assert.equal(normalized.can_request_execution, false);
  assert.equal(normalized.description, "Execution provider contract.");
  assert.equal(normalized.display_name, "core.no_op_provider");
  assert.equal(normalized.docs_path, "");
  assert.equal(
    normalized.safe_status_message,
    "Provider is pending and cannot execute in C09C.",
  );
  assert.equal(normalized.secret_requirement.secret_read_allowed, false);
  assert.equal(
    Object.hasOwn(normalized.secret_requirement, "provider_credential_declared"),
    false,
  );
  assert.doesNotMatch(
    JSON.stringify(normalized),
    /token=raw|Authorization|https:\/\/private|credential=raw|\.env\.production/,
  );
});

test("provider access normalization forces disabled submit state", () => {
  const state = access({
    can_request_execution: true,
    executable: true,
    safe_status_message: "token=raw http://private.invalid",
  });

  assert.equal(isExecutionProviderExecutable(state), false);
  assert.equal(canRequestExecution(state), false);
  assert.equal(state.executable, false);
  assert.equal(state.can_request_execution, false);
  assert.equal(
    state.safe_status_message,
    "Execution Provider contract is readable; execution is disabled.",
  );
});

test("execution provider responses normalize safe registry and access items", () => {
  const registry = normalizeExecutionProviderRegistryResponse({
    count: 1,
    items: [provider()],
  });
  const me = normalizeUserExecutionProvidersResponse({
    count: 1,
    is_owner_full_access: true,
    items: [access()],
    role: "owner",
    user_id: 1,
  });

  assert.equal(registry.count, 1);
  assert.equal(registry.items[0].provider_key, "core.no_op_provider");
  assert.equal(me.count, 1);
  assert.equal(me.items[0].provider_key, "core.no_op_provider");
});

test("execution provider lookup matches module adapter action contracts", () => {
  const providerFixture = provider();
  const accessFixture = access();

  assert.equal(
    findExecutionProviderContractForAction(
      {
        actionKey: baseActionContract.action_key,
        adapterKey: "business.products.placeholder.adapter",
        moduleKey: "business.products",
      },
      [providerFixture],
    )?.provider_key,
    "core.no_op_provider",
  );
  assert.equal(
    findExecutionProviderAccessStateForAction(
      {
        actionKey: baseActionContract.action_key,
        adapterKey: "business.products.placeholder.adapter",
        moduleKey: "business.products",
      },
      [accessFixture],
    )?.provider_key,
    "core.no_op_provider",
  );
});

test("execution required action shows waiting C09 when no provider matches", () => {
  const state = getExecutionProviderActionState({
    accessState: null,
    requiresExecutionProvider: true,
  });
  const adapterState = getActionContractState(
    baseActionContract,
    adapterAccess(),
    null,
  );

  assert.equal(state.state, "provider_pending");
  assert.equal(state.message, "waiting for C09 Execution Provider");
  assert.equal(state.executable, false);
  assert.equal(state.can_request_execution, false);
  assert.equal(adapterState.state, "provider_pending");
  assert.equal(adapterState.can_request_execution, false);
});

test("approval required action shows waiting C12 and stays disabled", () => {
  const providerAccess = access({
    approval_status: "blocked_approval_required",
    block_reason: "blocked_approval_required",
    no_execute_reason: "waiting_c12_approval_gate",
    requires_approval: true,
    safe_status_message: "Waiting for C12 Approval Gate.",
  });
  const actionState = getExecutionProviderActionState({
    accessState: providerAccess,
  });
  const adapterState = getActionContractState(
    { ...baseActionContract, requires_approval: true },
    adapterAccess(providerAccess, { requires_approval: true }),
    providerAccess,
  );

  assert.equal(actionState.state, "approval_required");
  assert.equal(actionState.message, "waiting for C12 Approval Gate");
  assert.equal(adapterState.state, "approval_required");
  assert.equal(adapterState.executable, false);
});

test("secret required action shows waiting C14 and stays disabled", () => {
  const providerAccess = access({
    block_reason: "secret_rules_required",
    no_execute_reason: "waiting_c14_secret_rules",
    requires_secret: true,
    secret_binding_status: "secret_rules_required",
    safe_status_message: "Waiting for C14 Secret Rules.",
  });
  const actionState = getExecutionProviderActionState({
    accessState: providerAccess,
  });
  const adapterState = getActionContractState(
    baseActionContract,
    adapterAccess(providerAccess),
    providerAccess,
  );

  assert.equal(actionState.state, "secret_required");
  assert.equal(actionState.message, "waiting for C14 Secret Rules");
  assert.equal(adapterState.state, "secret_required");
  assert.equal(adapterState.can_request_execution, false);
});

test("execution provider action state matrix covers C09D blocking statuses", () => {
  const cases = [
    {
      expectedMessage: "waiting for C09 Execution Provider",
      expectedNoExecute: "provider_pending",
      expectedState: "provider_pending",
      input: {
        accessState: null,
        requiresExecutionProvider: true,
      },
    },
    {
      expectedMessage: "waiting for C09 Execution Provider",
      expectedNoExecute: "c09b_no_execute_provider_contract_only",
      expectedState: "execution_provider_required",
      input: {
        accessState: access({
          block_reason: "execution_provider_required",
          no_execute_reason: "c09b_no_execute_provider_contract_only",
        }),
        requiresExecutionProvider: true,
      },
    },
    {
      expectedMessage: "waiting for C12 Approval Gate",
      expectedNoExecute: "waiting_c12_approval_gate",
      expectedState: "approval_required",
      input: {
        accessState: access({
          approval_status: "blocked_approval_required",
          block_reason: "blocked_approval_required",
          no_execute_reason: "waiting_c12_approval_gate",
          requires_approval: true,
        }),
      },
    },
    {
      expectedMessage: "waiting for C14 Secret Rules",
      expectedNoExecute: "waiting_c14_secret_rules",
      expectedState: "secret_required",
      input: {
        accessState: access({
          block_reason: "secret_rules_required",
          no_execute_reason: "waiting_c14_secret_rules",
          requires_secret: true,
          secret_binding_status: "secret_rules_required",
        }),
      },
    },
    {
      expectedMessage: "waiting for C18 Scope Adapter",
      expectedNoExecute: "waiting_c18_scope_adapter",
      expectedState: "scope_required",
      input: {
        accessState: access({
          block_reason: "scope_adapter_pending",
          no_execute_reason: "waiting_c18_scope_adapter",
          requires_scope: true,
          scope_status: "scope_adapter_pending",
        }),
      },
    },
  ];

  for (const testCase of cases) {
    const state = getExecutionProviderActionState(testCase.input);

    assert.equal(state.state, testCase.expectedState);
    assert.equal(state.message, testCase.expectedMessage);
    assert.equal(state.no_execute_reason, testCase.expectedNoExecute);
    assert.equal(state.button_label, "Provider unavailable");
    assert.equal(state.disabled, true);
    assert.equal(state.executable, false);
    assert.equal(state.can_request_execution, false);
  }
});

test("scope required action shows waiting C18 and stays disabled", () => {
  const providerAccess = access({
    block_reason: "scope_adapter_pending",
    no_execute_reason: "waiting_c18_scope_adapter",
    requires_scope: true,
    scope_status: "scope_adapter_pending",
    safe_status_message: "Waiting for C18 Scope Adapter.",
  });
  const actionState = getExecutionProviderActionState({
    accessState: providerAccess,
  });
  const adapterState = getActionContractState(
    baseActionContract,
    adapterAccess(providerAccess),
    providerAccess,
  );

  assert.equal(actionState.state, "scope_required");
  assert.equal(actionState.message, "waiting for C18 Scope Adapter");
  assert.equal(adapterState.state, "scope_required");
  assert.equal(adapterState.executable, false);
});

test("hidden locked and unavailable provider states never render executable state", () => {
  for (const providerAccess of [
    access({
      hidden: true,
      no_execute_reason: "hidden",
      provider_access_state: "hidden",
      visible: false,
    }),
    access({
      locked: true,
      missing_permissions: ["products.read"],
      no_execute_reason: "missing_permission",
      provider_access_state: "locked",
    }),
    access({
      no_execute_reason: "provider_unavailable",
      provider_access_state: "unavailable",
      provider_status: "provider_unavailable",
      unavailable: true,
    }),
  ]) {
    const state = getExecutionProviderActionState({
      accessState: providerAccess,
      requiresExecutionProvider: true,
    });
    assert.equal(state.executable, false);
    assert.equal(state.can_request_execution, false);
    assert.notEqual(state.state, "no_execute");
  }
});

test("execution provider status shell renders safe status fields and no submit hook", () => {
  const shellSource = readFileSync(
    "frontend/src/components/execution-provider-status-shell.tsx",
    "utf8",
  );

  assert.match(shellSource, /role="status"/);
  assert.match(shellSource, /getExecutionProviderStatusLabel/);
  assert.match(shellSource, /provider_access_state/);
  assert.match(shellSource, /no_execute_reason/);
  assert.match(shellSource, /safe_status_message/);
  assert.match(shellSource, /actionState\.button_label/);
  assert.match(shellSource, /<button disabled type="button">/);
  assert.doesNotMatch(shellSource, /onClick|onSubmit|formAction/);
});

test("execution provider status shell is disabled and contains no client call", () => {
  const shellSource = readFileSync(
    "frontend/src/components/execution-provider-status-shell.tsx",
    "utf8",
  );

  assert.match(shellSource, /ExecutionProviderStatusShell/);
  assert.match(shellSource, /getExecutionProviderActionState/);
  assert.match(shellSource, /<button disabled type="button">/);
  assert.doesNotMatch(
    shellSource,
    /apiRequest|fetch\(|method:\s*["'](?:POST|PUT|PATCH|DELETE)["']/,
  );
  assert.doesNotMatch(
    shellSource,
    /Authorization|Bearer|password|credential=|provider_url|https?:\/\/|webhook_url|token=/i,
  );
});

test("module adapter shell is execution-aware but no-execute", () => {
  const shellSource = readFileSync(
    "frontend/src/components/module-adapter-shell.tsx",
    "utf8",
  );
  const providerSource = readFileSync(
    "frontend/src/components/adapter-access-provider.tsx",
    "utf8",
  );

  assert.match(shellSource, /ExecutionProviderStatusShell/);
  assert.match(shellSource, /findExecutionProviderAccessStateForAction/);
  assert.match(shellSource, /findExecutionProviderContractForAction/);
  assert.doesNotMatch(
    shellSource,
    /apiRequest|fetch\(|method:\s*["'](?:POST|PUT|PATCH|DELETE)["']/,
  );
  assert.match(providerSource, /useFrontendCapabilityState/);
  assert.match(providerSource, /executionProviders/);
  assert.match(providerSource, /executionProviderAccessItems/);
  assert.doesNotMatch(
    providerSource,
    /getExecutionProviderRegistry|getMyExecutionProviders|apiRequest|fetch\(/,
  );
});

test("adapter contract normalization remains intact with C09C provider state", () => {
  const adapterFixture = normalizeAdapterContract({
    action_contracts: [baseActionContract],
    adapter_key: "business.products.placeholder.adapter",
    adapter_status: "contract_ready",
    adapter_version: "1.0.0",
    description: "Adapter contract.",
    display_name: "Products Placeholder Adapter",
    docs_path: "docs/C08_MODULE_ADAPTER_BACKEND.md",
    lifecycle: "contract_ready",
    manifest_version: "v1",
    module_key: "business.products",
    supported_surfaces: ["module_page", "action_panel"],
    unavailable_behavior: "adapter_pending",
  });
  assert.notEqual(adapterFixture, null);
  const providerAccess = access();
  const actionState = getActionContractState(
    adapterFixture.action_contracts[0],
    adapterAccess(providerAccess),
    providerAccess,
  );

  assert.equal(actionState.executable, false);
  assert.equal(actionState.can_request_execution, false);
  assert.equal(actionState.state, "execution_provider_required");
  assert.equal(actionState.no_execute_reason, "c09b_no_execute_provider_contract_only");
});
