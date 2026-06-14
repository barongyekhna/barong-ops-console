import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";
import {
  navigationItems,
  navigationModuleRecords,
} from "../../frontend/src/lib/navigation.ts";
import {
  getModuleRouteDecision,
  getNavigationStateForModule,
} from "../../frontend/src/lib/module-registry.ts";
import {
  adapterContainsUnsafeDependencyValue,
  canExposeAdapterMetadata,
  findAdapterAccessState,
  getActionContractState,
  getAdapterStatusLabel,
  getAdapterSurfaceState,
  getSafeDependencyNames,
  isAdapterExecutable,
  isAdapterLocked,
  isAdapterUnavailable,
  isAdapterVisible,
  isFutureExampleAdapterEnabled,
  normalizeAdapterAccessState,
  normalizeAdapterContract,
} from "../../frontend/src/lib/module-adapter.ts";
import { canShowPermissionManagementEntry } from "../../frontend/src/lib/permission-management.ts";
import {
  getPermissionAccessState,
  isOwnerFullAccess,
} from "../../frontend/src/lib/permissions.ts";

const ownerPermissions = {
  assignments: [],
  is_owner_full_access: true,
  permission_keys: ["*"],
  scope_summary: [],
};

const noPermissions = {
  assignments: [],
  is_owner_full_access: false,
  permission_keys: [],
  scope_summary: [],
};

const usersManagePermissions = {
  assignments: [
    {
      permission_key: "users.manage",
      scope_key: "*",
      scope_type: "global",
    },
  ],
  is_owner_full_access: false,
  permission_keys: ["users.manage"],
  scope_summary: [],
};

const permissionsReadPermissions = {
  assignments: [
    {
      permission_key: "permissions.read",
      scope_key: "*",
      scope_type: "global",
    },
  ],
  is_owner_full_access: false,
  permission_keys: ["permissions.read"],
  scope_summary: [],
};

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

function adapter(raw = {}) {
  const normalized = normalizeAdapterContract({
    action_contracts: [baseActionContract],
    actions: [
      {
        action_key: "business.products.placeholder.prepare",
        capability_key: "business.products.placeholder",
        description: "Declare future product workspace preparation.",
        executable_before_c09: true,
        module_key: "business.products",
        operation_log_action: "business.products.placeholder.prepare",
        required_permission: "products.read",
        requires_approval: false,
        requires_execution_provider: true,
        risk_level: "medium",
        status: "adapter_pending",
      },
    ],
    adapter_key: "business.products.placeholder.adapter",
    adapter_status: "adapter_pending",
    adapter_version: "1.0.0",
    api_bindings: [
      {
        api_key: "business.products.no_api",
        api_namespace: "no_api",
        method: "NO_API",
        module_key: "business.products",
        no_api: true,
        path: "no_api",
        status: "adapter_pending",
      },
    ],
    approval_requirements: {
      approval_provider_state: "not_implemented_c08b",
      approval_reason_required: false,
      high_risk_action_policy: "not_required",
      requires_approval: false,
    },
    capabilities: [
      {
        capability_key: "business.products.placeholder",
        description: "Declare future product workspace placeholder.",
        display_name: "View product placeholder",
        module_key: "business.products",
        required_permission: "products.read",
        surfaces: ["module_page", "status_widget"],
      },
    ],
    data_contracts: [
      {
        contract_key: "business.products.placeholder.v1",
        contract_version: "1.0.0",
        module_key: "business.products",
        object_type: "product_placeholder",
        owner_module: "business.products",
        read_boundary: ["module_metadata"],
        write_boundary: [],
      },
    ],
    dependency_declarations: [],
    description: "Planned product workspace adapter placeholder.",
    display_name: "Products Placeholder Adapter",
    docs_path: "docs/C08_MODULE_ADAPTER_BACKEND.md",
    execution_requirements: {
      executable_before_c09: false,
      execution_provider_state: "required_not_implemented_c08b",
      provider_contract_ref: "business.products.execution.v1",
      queue_required: true,
      requires_execution_provider: true,
      result_contract_ref: null,
    },
    input_contracts: [
      {
        action_key: "business.products.placeholder.prepare",
        contract_key: "business.products.placeholder.input.v1",
        optional_fields: [],
        redaction_policy: "safe_fields_only",
        required_fields: [],
        sensitive_fields: [],
        validation_rules: ["declared_only"],
      },
    ],
    lifecycle: "adapter_pending",
    manifest_version: "v1",
    module_key: "business.products",
    nav_bindings: [
      {
        denied_behavior: "show_locked",
        label: "Products",
        module_key: "business.products",
        nav_key: "business.products.main",
        required_permission: "products.read",
        route: "/products",
        status: "adapter_pending",
        unavailable_behavior: "planned",
      },
    ],
    output_contracts: [
      {
        action_key: "business.products.placeholder.prepare",
        contract_key: "business.products.placeholder.output.v1",
        operation_log_projection: ["module_key", "adapter_status"],
        redaction_policy: "safe_fields_only",
        safe_summary_fields: ["module_key", "adapter_status"],
        sensitive_fields: [],
      },
    ],
    pages: [
      {
        module_key: "business.products",
        page_key: "business.products.placeholder",
        required_permission: "products.read",
        route: "/products",
        route_namespace: "/products",
        status: "adapter_pending",
        surface: "module_page",
        unavailable_behavior: "adapter_pending",
      },
    ],
    route_bindings: [
      {
        module_key: "business.products",
        path: "/products",
        required_permission: "products.read",
        route_key: "business.products.placeholder",
        route_namespace: "/products",
        status: "adapter_pending",
        surface: "module_page",
      },
    ],
    supported_surfaces: ["navigation", "module_page", "action_panel", "status_widget"],
    unavailable_behavior: "adapter_pending",
    ...raw,
  });
  assert.notEqual(normalized, null);
  return normalized;
}

function access(adapterFixture, raw = {}) {
  const normalized = normalizeAdapterAccessState({
    action_contracts: adapterFixture.action_contracts,
    adapter_access_state: "available",
    adapter_key: adapterFixture.adapter_key,
    adapter_status: adapterFixture.adapter_status,
    available_actions: ["should.not.execute"],
    available_surfaces: ["navigation", "module_page", "status_widget"],
    disabled_surfaces: ["action_panel"],
    execution_provider_state: "required_not_implemented_c08b",
    hidden: false,
    locked: false,
    missing_permissions: [],
    module_key: adapterFixture.module_key,
    reason: "Adapter contract metadata is available.",
    required_permissions: ["products.read"],
    requires_approval: false,
    requires_execution_provider: true,
    supported_surfaces: adapterFixture.supported_surfaces,
    unavailable: false,
    unavailable_actions: [],
    visible: true,
    ...raw,
  });
  assert.notEqual(normalized, null);
  return normalized;
}

test("backend proxy precisely allows C08B module adapter registry paths", () => {
  assert.equal(
    isAllowedBackendProxyPath("GET", ["module-adapters", "registry"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["module-adapters", "me"]),
    true,
  );
});

test("backend proxy rejects broad module adapter paths", () => {
  assert.equal(
    isAllowedBackendProxyPath("GET", ["module-adapters", "not-allowed"]),
    false,
  );
  assert.equal(
    isAllowedBackendProxyPath("POST", ["module-adapters", "registry"]),
    false,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["module-adapters", "me", "x"]),
    false,
  );
});

test("backend proxy precisely allows C14 external dependency read paths", () => {
  assert.equal(
    isAllowedBackendProxyPath("GET", ["external-dependencies", "registry"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["external-dependencies", "proposals"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["external-dependencies", "bindings"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", [
      "external-dependencies",
      "binding-rules",
    ]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", [
      "external-dependencies",
      "dependency-graph",
    ]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", [
      "external-dependencies",
      "binding-validation",
    ]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", [
      "external-dependencies",
      "binding-audit",
    ]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("POST", ["external-dependencies", "registry"]),
    false,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["external-dependencies", "register"]),
    false,
  );
});

test("verify-foundation checks C08 module adapter proxy allowlist", () => {
  const verifier = readFileSync(
    "frontend/scripts/verify-foundation.mjs",
    "utf8",
  );
  assert.match(verifier, /module-adapters\/registry/);
  assert.match(verifier, /module-adapters\/me/);
  assert.match(verifier, /ALLOWED_MODULE_ADAPTER_REGISTRY_PATHS/);
  assert.match(verifier, /\/module-adapters\/\*/);
});

test("verify-foundation protects C08D adapter contract files and no-live rules", () => {
  const verifier = readFileSync(
    "frontend/scripts/verify-foundation.mjs",
    "utf8",
  );

  assert.match(verifier, /adapter-access-provider\.tsx/);
  assert.match(verifier, /module-adapter-shell\.tsx/);
  assert.match(verifier, /module-adapter-api\.ts/);
  assert.match(verifier, /module-adapter\.ts/);
  assert.match(verifier, /execution-provider-status-shell\.tsx/);
  assert.match(verifier, /execution-provider-api\.ts/);
  assert.match(verifier, /execution-provider\.ts/);
  assert.match(verifier, /execution-provider\.test\.mjs/);
  assert.match(verifier, /module-adapter\.test\.mjs/);
  assert.match(verifier, /module-isolation\.test\.mjs/);
  assert.match(verifier, /live n8n\/WooCommerce\/MinIO\/Filebrowser/);
  assert.match(verifier, /K01 or P-series menus/);
});

test("verify-foundation keeps C07 module checks and C05 C06 permission checks", () => {
  const verifier = readFileSync(
    "frontend/scripts/verify-foundation.mjs",
    "utf8",
  );
  assert.match(verifier, /modules\/registry/);
  assert.match(verifier, /modules\/me/);
  assert.match(verifier, /permissions\/me/);
  assert.match(verifier, /permissions\/registry/);
  assert.match(verifier, /assignments/);
});

test("adapter_pending, draft, disabled, and deprecated adapters are not executable", () => {
  for (const status of ["adapter_pending", "draft", "disabled", "deprecated"]) {
    const fixture = adapter({
      adapter_status: status,
      lifecycle: status,
    });
    const state = access(fixture, {
      adapter_access_state:
        status === "adapter_pending" ? "adapter_pending" : "unavailable",
      adapter_status: status,
      unavailable: true,
    });

    assert.equal(isAdapterExecutable(state), false);
    assert.equal(isAdapterUnavailable(state), true);
    assert.equal(state.available_actions.length, 0);
  }
});

test("execution required action contracts are unavailable before C09", () => {
  const fixture = adapter({
    adapter_status: "contract_ready",
    lifecycle: "contract_ready",
  });
  const state = access(fixture, {
    adapter_access_state: "unavailable",
    adapter_status: "contract_ready",
    unavailable: true,
  });
  const actionState = getActionContractState(fixture.action_contracts[0], state);

  assert.equal(actionState.executable, false);
  assert.equal(actionState.disabled, true);
  assert.equal(actionState.can_request_execution, false);
  assert.equal(actionState.state, "provider_pending");
  assert.equal(actionState.execution_message, "waiting for C09 Execution Provider");
  assert.deepEqual(state.available_actions, []);
  assert.deepEqual(state.unavailable_actions, ["should.not.execute"]);
});

test("approval required action contracts show pending C12 and stay non-executable", () => {
  const fixture = adapter({
    action_contracts: [
      {
        ...baseActionContract,
        requires_approval: true,
        requires_execution_provider: false,
      },
    ],
    approval_requirements: {
      approval_provider_state: "not_implemented_c08b",
      approval_reason_required: true,
      high_risk_action_policy: "future_c12_required",
      requires_approval: true,
    },
  });
  const state = access(fixture, {
    requires_approval: true,
    requires_execution_provider: false,
  });
  const actionState = getActionContractState(fixture.action_contracts[0], state);

  assert.equal(actionState.executable, false);
  assert.equal(actionState.state, "approval_required");
  assert.equal(actionState.can_request_execution, false);
  assert.equal(actionState.approval_message, "waiting for C12 Approval Gate");
});

test("owner can see admin adapter metadata and non-owner admin adapters are hidden", () => {
  const adminAdapter = adapter({
    adapter_key: "admin.users.adapter",
    adapter_status: "sealed",
    lifecycle: "sealed",
    module_key: "admin.users",
    supported_surfaces: ["navigation", "module_page", "action_panel"],
  });
  const ownerState = access(adminAdapter, {
    adapter_access_state: "available",
    adapter_status: "sealed",
    module_key: "admin.users",
    requires_execution_provider: false,
  });
  const hiddenState = access(adminAdapter, {
    action_contracts: [],
    adapter_access_state: "hidden",
    adapter_status: "sealed",
    hidden: true,
    module_key: "admin.users",
    supported_surfaces: [],
    visible: false,
  });

  assert.equal(
    canExposeAdapterMetadata(adminAdapter, ownerState, {
      isOwnerFullAccess: true,
    }),
    true,
  );
  assert.equal(
    canExposeAdapterMetadata(adminAdapter, hiddenState, {
      isOwnerFullAccess: false,
    }),
    false,
  );
  assert.equal(
    canExposeAdapterMetadata(adminAdapter, null, {
      adapterAccessUnknown: true,
      isOwnerFullAccess: false,
    }),
    false,
  );
});

test("business adapter without permission remains visible but locked", () => {
  const fixture = adapter();
  const locked = access(fixture, {
    adapter_access_state: "locked",
    locked: true,
    missing_permissions: ["products.read"],
  });

  assert.equal(isAdapterVisible(locked), true);
  assert.equal(isAdapterLocked(locked), true);
  assert.equal(isAdapterExecutable(locked), false);
});

test("missing adapter access state safely downgrades to unknown unavailable", () => {
  const fixture = adapter();
  const surfaceState = getAdapterSurfaceState(fixture, null, "module_page");

  assert.equal(findAdapterAccessState(fixture.adapter_key, []), null);
  assert.equal(surfaceState.state, "unknown");
  assert.equal(surfaceState.available, false);
  assert.equal(surfaceState.disabled, true);
});

test("dependency declarations keep only safe dynamic dependency keys", () => {
  const fixture = adapter({
    dependency_declarations: [
      {
        dependency_key: "unknown.ai_service",
        dependency_type: "integration",
        live_connection_allowed: true,
        provider_status: "declared_only",
        safe_unavailable_message: "safe declaration",
      },
      {
        dependency_key: "future_storage_provider",
        dependency_type: "integration",
        live_connection_allowed: false,
        provider_status: "declared_only",
        safe_unavailable_message: "safe declaration",
      },
      {
        dependency_key: "token",
        dependency_type: "secret",
        safe_unavailable_message: "Authorization header",
      },
      {
        dependency_key: "https://example.invalid/provider",
        dependency_type: "url",
        safe_unavailable_message: "url",
      },
    ],
  });

  assert.deepEqual(getSafeDependencyNames(fixture.dependency_declarations), [
    "unknown.ai_service",
    "future_storage_provider",
  ]);
  assert.equal(adapterContainsUnsafeDependencyValue(fixture), false);
  assert.equal(
    fixture.dependency_declarations.every(
      (dependency) => dependency.live_connection_allowed === false,
    ),
    true,
  );
  assert.doesNotMatch(
    JSON.stringify(fixture.dependency_declarations),
    /token|password|authorization|credential|env|https?:|webhook|url/i,
  );
});

test("role defaults and super_admin do not become implicit adapter access", () => {
  const adminAdapter = adapter({
    adapter_key: "admin.permissions.adapter",
    adapter_status: "sealed",
    lifecycle: "sealed",
    module_key: "admin.permissions",
  });
  const businessState = access(adapter(), {
    adapter_access_state: "locked",
    locked: true,
    missing_permissions: ["products.read"],
  });

  assert.equal(isAdapterLocked(businessState), true);
  assert.equal(
    canExposeAdapterMetadata(adminAdapter, null, {
      adapterAccessUnknown: true,
      isOwnerFullAccess: false,
    }),
    false,
  );
});

test("AdapterStatusBadge labels cover draft pending disabled deprecated and sealed", () => {
  assert.equal(getAdapterStatusLabel("draft"), "Draft");
  assert.equal(getAdapterStatusLabel("adapter_pending"), "Adapter pending");
  assert.equal(getAdapterStatusLabel("disabled"), "Disabled");
  assert.equal(getAdapterStatusLabel("deprecated"), "Deprecated");
  assert.equal(getAdapterStatusLabel("sealed"), "Sealed");
});

test("action contract state does not expose executable payload", () => {
  const fixture = adapter();
  const state = access(fixture);
  const actionState = getActionContractState(fixture.action_contracts[0], state);

  assert.equal(actionState.executable, false);
  assert.equal(Object.hasOwn(actionState, "payload"), false);
  assert.equal(state.available_actions.length, 0);
});

test("module-adapter API client and shell do not create action execution calls", () => {
  const apiSource = readFileSync(
    "frontend/src/lib/module-adapter-api.ts",
    "utf8",
  );
  const shellSource = readFileSync(
    "frontend/src/components/module-adapter-shell.tsx",
    "utf8",
  );
  const statusShellSource = readFileSync(
    "frontend/src/components/execution-provider-status-shell.tsx",
    "utf8",
  );

  assert.match(apiSource, /apiRequest<unknown>\("\/module-adapters\/registry"/);
  assert.match(apiSource, /apiRequest<unknown>\("\/module-adapters\/me"/);
  assert.doesNotMatch(apiSource, /method:\s*["'](?:POST|PUT|PATCH|DELETE)["']/);
  assert.doesNotMatch(
    apiSource,
    /\/module-adapters\/[^"']*(?:actions?|execute|execution|run)/i,
  );
  assert.doesNotMatch(
    shellSource,
    /apiRequest|fetch\(|method:\s*["'](?:POST|PUT|PATCH|DELETE)["']/,
  );
  assert.match(shellSource, /ExecutionProviderStatusShell/);
  assert.match(statusShellSource, /<button disabled type="button">/);
  assert.doesNotMatch(
    shellSource,
    /live\s+(?:n8n|woocommerce|minio|filebrowser)\s+(?:action|provider|connected)/i,
  );
});

test("AdapterUnavailableNotice source does not expose internal credentials", () => {
  const source = readFileSync(
    "frontend/src/components/module-adapter-shell.tsx",
    "utf8",
  );
  const statusShellSource = readFileSync(
    "frontend/src/components/execution-provider-status-shell.tsx",
    "utf8",
  );
  assert.doesNotMatch(
    `${source}\n${statusShellSource}`,
    /Authorization|Bearer|password|credential|api[_ -]?key|provider_url|https?:\/\/|webhook/i,
  );
});

test("K01 and P-series future examples are not default enabled", () => {
  const pendingK01 = adapter({
    adapter_key: "k01.product_knowledge.adapter",
    adapter_status: "adapter_pending",
    lifecycle: "adapter_pending",
    module_key: "k01.product_knowledge",
  });
  const enabledK01 = adapter({
    adapter_key: "k01.product_knowledge.adapter",
    adapter_status: "contract_ready",
    lifecycle: "contract_ready",
    module_key: "k01.product_knowledge",
  });
  const pendingP01 = adapter({
    adapter_key: "p01.product_page.adapter",
    adapter_status: "adapter_pending",
    lifecycle: "adapter_pending",
    module_key: "p01.product_page",
  });
  const enabledP01 = adapter({
    adapter_key: "p01.product_page.adapter",
    adapter_status: "test_ready",
    lifecycle: "test_ready",
    module_key: "p01.product_page",
  });
  const moduleKeys = navigationItems.map((entry) => entry.module_key);

  assert.equal(isFutureExampleAdapterEnabled(pendingK01), false);
  assert.equal(isFutureExampleAdapterEnabled(enabledK01), true);
  assert.equal(isFutureExampleAdapterEnabled(pendingP01), false);
  assert.equal(isFutureExampleAdapterEnabled(enabledP01), true);
  assert.equal(moduleKeys.some((key) => /k01|p0[1-8]|p_series/i.test(key)), false);
});

test("C07 module-isolation route guard regression still denies locked business", () => {
  const decision = getModuleRouteDecision(
    noPermissions,
    "/jobs",
    navigationModuleRecords,
    [],
    { moduleAccessUnknown: true },
  );

  assert.equal(decision.canEnter, false);
  assert.equal(decision.noticeType, "no_permission");
  assert.equal(decision.isLocked, true);
});

test("C06 permission-management proxy regression still allows assignment APIs only", () => {
  assert.equal(
    isAllowedBackendProxyPath("GET", [
      "permissions",
      "users",
      "42",
      "assignments",
    ]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("POST", ["permissions", "wildcard"]),
    false,
  );
});

test("C05 permission helper regression keeps owner full access explicit", () => {
  assert.equal(isOwnerFullAccess(ownerPermissions), true);
  assert.equal(isOwnerFullAccess(noPermissions), false);
});

test("User Management remains owner-only", () => {
  const usersModule = navigationModuleRecords.find(
    (entry) => entry.module_key === "admin.users",
  );
  assert.equal(usersModule.owner_only, true);
  assert.deepEqual(getPermissionAccessState(noPermissions, usersModule), {
    canAccess: false,
    isLocked: false,
    isVisible: false,
  });
  assert.deepEqual(
    getPermissionAccessState(usersManagePermissions, usersModule),
    {
      canAccess: false,
      isLocked: false,
      isVisible: false,
    },
  );
});

test("Permission Management remains owner-only", () => {
  const permissionManagement = navigationModuleRecords.find(
    (entry) => entry.module_key === "admin.permissions",
  );
  assert.equal(permissionManagement.owner_only, true);
  assert.equal(canShowPermissionManagementEntry(ownerPermissions), true);
  assert.equal(
    canShowPermissionManagementEntry(permissionsReadPermissions),
    false,
  );
  assert.equal(
    getNavigationStateForModule(
      permissionsReadPermissions,
      permissionManagement,
      [],
      { moduleAccessUnknown: true },
    ).isVisible,
    false,
  );
});
