import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";
import {
  navigationItems,
  navigationModuleRecords,
} from "../../frontend/src/lib/navigation.ts";
import {
  MODULE_NO_PERMISSION_DESCRIPTION,
  MODULE_NO_PERMISSION_TITLE,
  MODULE_UNAVAILABLE_DESCRIPTION,
  MODULE_UNAVAILABLE_TITLE,
} from "../../frontend/src/lib/module-notices.ts";
import {
  assertNavigationModulesRegistered,
  canEnterModuleRoute,
  getModuleRouteDecision,
  getNavigationStateForModule,
  isAdminOrSystemModule,
  isBusinessModule,
  isModuleHidden,
  isModuleLocked,
  isModuleUnavailable,
  isModuleVisible,
  normalizeModuleAccessState,
  normalizeModuleManifest,
} from "../../frontend/src/lib/module-registry.ts";
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

const operationLogsReadPermissions = {
  assignments: [
    {
      permission_key: "operation_logs.read",
      scope_key: "*",
      scope_type: "global",
    },
  ],
  is_owner_full_access: false,
  permission_keys: ["operation_logs.read"],
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

const reviewsReadPermissions = {
  assignments: [
    {
      permission_key: "reviews.read",
      scope_key: "*",
      scope_type: "global",
    },
  ],
  is_owner_full_access: false,
  permission_keys: ["reviews.read"],
  scope_summary: [],
};

const wildcardNonOwnerPermissions = {
  assignments: [
    {
      permission_key: "*",
      scope_key: "*",
      scope_type: "global",
    },
  ],
  is_owner_full_access: false,
  permission_keys: ["*"],
  scope_summary: [],
};

function item(moduleKey) {
  return navigationModuleRecords.find(
    (entry) => entry.module_key === moduleKey,
  );
}

function access(raw) {
  const normalized = normalizeModuleAccessState({
    denied_behavior: "show_locked",
    executable: false,
    hidden: false,
    locked: false,
    missing_permissions: [],
    reason: "test fixture",
    required_permissions: [],
    unavailable: false,
    visible: true,
    ...raw,
  });
  assert.notEqual(normalized, null);
  return normalized;
}

function manifest(raw) {
  const normalized = normalizeModuleManifest({
    api_namespace: "no_api",
    category: "business",
    denied_behavior: "show_locked",
    display_name: raw.module_key,
    docs_path: "docs/C07_MODULE_REGISTRY_BACKEND.md",
    lifecycle: "sealed",
    navigation: {
      default_visible: true,
      group: "Test",
      icon: "Boxes",
      label: raw.module_key,
      order: 10,
      owner_only: false,
    },
    no_api: true,
    required_permissions: [],
    route_namespace: "/test",
    status: "enabled",
    unavailable_behavior: "show_unavailable",
    ...raw,
  });
  assert.notEqual(normalized, null);
  return normalized;
}

const registryItems = [
  manifest({
    category: "experimental",
    denied_behavior: "hide_when_denied",
    module_key: "experimental.foundation_demo",
    required_permissions: ["jobs.create"],
    route_namespace: "/foundation-demo",
    status: "enabled",
  }),
  manifest({
    category: "integration",
    denied_behavior: "hide_when_denied",
    external_dependencies: ["n8n"],
    module_key: "integration.n8n_test_bridge",
    required_permissions: ["jobs.create"],
    route_namespace: "/n8n-test",
    status: "adapter_pending",
  }),
  manifest({
    category: "admin",
    denied_behavior: "hide_when_denied",
    module_key: "admin.users",
    required_permissions: ["users.manage"],
    route_namespace: "/users",
    status: "sealed",
  }),
  manifest({
    category: "admin",
    denied_behavior: "show_locked",
    module_key: "admin.permissions",
    required_permissions: ["permissions.read"],
    route_namespace: "/permissions",
    status: "sealed",
  }),
  manifest({
    category: "admin",
    denied_behavior: "show_locked",
    module_key: "admin.organizations",
    required_permissions: ["organizations.read"],
    route_namespace: "/organizations",
    status: "enabled",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    module_key: "business.approvals",
    required_permissions: ["reviews.read"],
    route_namespace: "/approvals",
    status: "enabled",
  }),
  manifest({
    category: "system",
    denied_behavior: "show_locked",
    module_key: "system.operation_logs",
    required_permissions: ["operation_logs.read"],
    route_namespace: "/operation-logs",
    status: "sealed",
  }),
];

test("backend proxy precisely allows C07B module registry paths", () => {
  assert.equal(
    isAllowedBackendProxyPath("GET", ["modules", "registry"]),
    true,
  );
  assert.equal(isAllowedBackendProxyPath("GET", ["modules", "me"]), true);
  assert.equal(isAllowedBackendProxyPath("GET", ["permissions", "me"]), true);
  assert.equal(
    isAllowedBackendProxyPath("GET", ["permissions", "registry"]),
    true,
  );
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
    isAllowedBackendProxyPath("PATCH", [
      "permissions",
      "users",
      "42",
      "assignments",
      "123e4567-e89b-12d3-a456-426614174000",
    ]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("POST", ["modules", "registry"]),
    false,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["modules", "anything-else"]),
    false,
  );
  assert.equal(isAllowedBackendProxyPath("GET", ["modules", "me", "x"]), false);
  assert.equal(
    isAllowedBackendProxyPath("GET", ["module-api", "business.approvals"]),
    false,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["n8n-test", "callback"]),
    false,
  );
});

test("verify-foundation checks C07 module proxy allowlist", () => {
  const verifier = readFileSync(
    "frontend/scripts/verify-foundation.mjs",
    "utf8",
  );
  assert.match(verifier, /modules\/registry/);
  assert.match(verifier, /modules\/me/);
  assert.match(verifier, /ALLOWED_MODULE_REGISTRY_PATHS/);
  assert.match(verifier, /module-isolation\.test\.mjs/);
  assert.match(verifier, /admin\.users/);
  assert.match(verifier, /admin\.permissions/);
  assert.match(verifier, /\/modules\/\*/);
});

test("module access helpers expose owner visible and non-owner hidden or locked states", () => {
  const ownerUsers = getNavigationStateForModule(
    ownerPermissions,
    item("admin.users"),
    [
      access({
        access_state: "available",
        category: "admin",
        denied_behavior: "hide_when_denied",
        module_key: "admin.users",
        route_namespace: "/users",
        status: "sealed",
      }),
    ],
  );
  const hiddenUsers = getNavigationStateForModule(
    noPermissions,
    item("admin.users"),
    [
      access({
        access_state: "hidden",
        category: "admin",
        denied_behavior: "hide_when_denied",
        hidden: true,
        module_key: "admin.users",
        route_namespace: "/users",
        status: "sealed",
        visible: false,
      }),
    ],
  );
  const lockedApprovals = getNavigationStateForModule(
    noPermissions,
    item("business.approvals"),
    [
      access({
        access_state: "locked",
        category: "business",
        locked: true,
        missing_permissions: ["reviews.read"],
        module_key: "business.approvals",
        route_namespace: "/approvals",
        status: "enabled",
      }),
    ],
  );

  assert.equal(isModuleVisible(ownerUsers), true);
  assert.equal(canEnterModuleRoute(ownerUsers), true);
  assert.equal(isModuleHidden(hiddenUsers), true);
  assert.equal(isAdminOrSystemModule(item("admin.users")), true);
  assert.equal(isModuleLocked(lockedApprovals), true);
  assert.equal(isBusinessModule(item("business.approvals")), true);
});

test("unavailable product modules are not enterable and diagnostics stay out of navigation", () => {
  const unavailableApprovals = getNavigationStateForModule(
    ownerPermissions,
    item("business.approvals"),
    [
      access({
        access_state: "unavailable",
        category: "business",
        module_key: "business.approvals",
        route_namespace: "/approvals",
        status: "unavailable",
        unavailable: true,
      }),
    ],
  );

  assert.equal(isModuleUnavailable(unavailableApprovals), true);
  assert.equal(unavailableApprovals.badge, "unavailable");
  assert.equal(canEnterModuleRoute(unavailableApprovals), false);
  assert.equal(item("experimental.foundation_demo"), undefined);
  assert.equal(item("integration.n8n_test_bridge"), undefined);
  assert.equal(item("business.products"), undefined);
  assert.equal(item("business.jobs"), undefined);
  assert.equal(item("core.dashboard"), undefined);
  assert.equal(item("admin.settings"), undefined);
});

test("unavailable modules use Module Unavailable decisions and stay non-enterable", () => {
  const unavailableApprovals = getNavigationStateForModule(
    ownerPermissions,
    item("business.approvals"),
    [
      access({
        access_state: "unavailable",
        category: "business",
        module_key: "business.approvals",
        route_namespace: "/approvals",
        status: "unavailable",
        unavailable: true,
      }),
    ],
  );
  const unavailableDecision = getModuleRouteDecision(
    ownerPermissions,
    "/approvals",
    navigationModuleRecords,
    [
      access({
        access_state: "unavailable",
        category: "business",
        module_key: "business.approvals",
        route_namespace: "/approvals",
        status: "unavailable",
        unavailable: true,
      }),
    ],
  );

  assert.equal(isModuleUnavailable(unavailableApprovals), true);
  assert.equal(unavailableApprovals.badge, "unavailable");
  assert.equal(canEnterModuleRoute(unavailableApprovals), false);
  assert.equal(unavailableDecision.noticeType, "module_unavailable");
  assert.equal(unavailableDecision.canEnter, false);
});

test("missing module access state safely degrades without exposing admin/system modules", () => {
  const adminOrganizations = getNavigationStateForModule(
    noPermissions,
    item("admin.organizations"),
    [],
    { moduleAccessUnknown: true },
  );
  const systemLogs = getNavigationStateForModule(
    operationLogsReadPermissions,
    item("system.operation_logs"),
    [],
    { moduleAccessUnknown: true },
  );
  const businessApprovals = getNavigationStateForModule(
    noPermissions,
    item("business.approvals"),
    [],
    { moduleAccessUnknown: true },
  );

  assert.equal(adminOrganizations.moduleAccessUnknown, true);
  assert.equal(adminOrganizations.isVisible, false);
  assert.equal(adminOrganizations.isHidden, true);
  assert.equal(systemLogs.isVisible, false);
  assert.equal(systemLogs.isHidden, true);
  assert.equal(businessApprovals.isVisible, true);
  assert.equal(businessApprovals.isLocked, true);
});

test("/modules/me failure fallback keeps non-owner admin/system hidden", () => {
  const missingUsers = getModuleRouteDecision(
    noPermissions,
    "/users",
    navigationModuleRecords,
    [],
    { moduleAccessUnknown: true },
  );
  const missingLogs = getModuleRouteDecision(
    noPermissions,
    "/operation-logs",
    navigationModuleRecords,
    [],
    { moduleAccessUnknown: true },
  );
  const missingApprovals = getModuleRouteDecision(
    noPermissions,
    "/approvals",
    navigationModuleRecords,
    [],
    { moduleAccessUnknown: true },
  );

  assert.equal(missingUsers.accessState, "hidden");
  assert.equal(missingUsers.noticeType, "no_permission");
  assert.equal(missingLogs.accessState, "hidden");
  assert.equal(missingLogs.noticeType, "no_permission");
  assert.equal(missingApprovals.isLocked, true);
  assert.equal(missingApprovals.canEnter, false);
  assert.equal(missingApprovals.noticeType, "no_permission");
});

test("external_dependencies normalization keeps only safe dependency names", () => {
  const normalized = manifest({
    external_dependencies: [
      "n8n",
      "woocommerce",
      "minio_url",
      "secret",
      "https://example.invalid/hook",
      "ai_provider",
    ],
    module_key: "business.safe_dependencies",
  });

  assert.deepEqual(normalized.external_dependencies, [
    "n8n",
    "woocommerce",
    "ai_provider",
  ]);
  assert.doesNotMatch(
    JSON.stringify(normalized.external_dependencies),
    /secret|token|password|env|url|http|authorization/i,
  );
  assert.doesNotMatch(
    JSON.stringify(registryItems),
    /secret|token|password|env|url|http|authorization|credential/i,
  );
});

test("every navigation module is registered and aligned with registry metadata", () => {
  const registryKeys = new Set(
    registryItems.map((manifestItem) => manifestItem.module_key),
  );

  assert.equal(
    navigationModuleRecords.every(
      (record) => record.module_key || record.core_shell_exception,
    ),
    true,
  );
  assert.equal(
    navigationModuleRecords.every((record) =>
      record.core_shell_exception ? true : registryKeys.has(record.module_key),
    ),
    true,
  );
  assert.doesNotThrow(() =>
    assertNavigationModulesRegistered(navigationModuleRecords, registryItems),
  );
  assert.throws(() =>
    assertNavigationModulesRegistered(
      [
        {
          ...item("business.approvals"),
          module_key: "business.missing",
        },
      ],
      registryItems,
    ),
  );
});

test("admin.users and admin.permissions remain hidden for non-owner and visible for owner", () => {
  const adminUsers = item("admin.users");
  const adminPermissions = item("admin.permissions");

  assert.equal(adminUsers.label, "Users");
  assert.equal(adminUsers.module_key, "admin.users");
  assert.equal(adminUsers.owner_only, true);
  assert.equal(adminUsers.denied_behavior, "hide_when_denied");
  assert.equal(adminUsers.category, "admin");
  assert.equal(adminPermissions.label, "Permissions");
  assert.equal(adminPermissions.module_key, "admin.permissions");
  assert.equal(adminPermissions.owner_only, true);
  assert.equal(adminPermissions.denied_behavior, "show_locked");
  assert.equal(adminPermissions.category, "admin");

  assert.equal(
    getNavigationStateForModule(noPermissions, adminUsers, [], {
      moduleAccessUnknown: true,
    }).isVisible,
    false,
  );
  assert.equal(
    getNavigationStateForModule(
      permissionsReadPermissions,
      adminPermissions,
      [],
      { moduleAccessUnknown: true },
    ).isVisible,
    false,
  );
  assert.equal(
    getNavigationStateForModule(ownerPermissions, adminUsers, [], {
      moduleAccessUnknown: true,
    }).isVisible,
    true,
  );
  assert.equal(
    getNavigationStateForModule(ownerPermissions, adminPermissions, [], {
      moduleAccessUnknown: true,
    }).isVisible,
    true,
  );
});

test("business modules stay locked for users without permission", () => {
  const approvalsState = getNavigationStateForModule(
    noPermissions,
    item("business.approvals"),
    [
      access({
        access_state: "locked",
        category: "business",
        locked: true,
        missing_permissions: ["reviews.read"],
        module_key: "business.approvals",
        route_namespace: "/approvals",
        status: "enabled",
      }),
    ],
  );

  assert.equal(approvalsState.isVisible, true);
  assert.equal(approvalsState.isLocked, true);
  assert.equal(approvalsState.badge, "locked");

  for (const record of navigationModuleRecords.filter(
    (entry) => entry.category === "business",
  )) {
    assert.equal(record.denied_behavior, "show_locked");
    assert.equal(
      getNavigationStateForModule(noPermissions, record, [], {
        moduleAccessUnknown: true,
      }).isVisible,
      true,
    );
  }
});

test("owner-only admin entries and system logs fail closed when module access is unknown", () => {
  for (const moduleKey of [
    "admin.users",
    "admin.organizations",
    "admin.permissions",
    "system.operation_logs",
  ]) {
    const state = getNavigationStateForModule(
      noPermissions,
      item(moduleKey),
      [],
      { moduleAccessUnknown: true },
    );
    assert.equal(state.isHidden, true);
    assert.equal(state.canEnter, false);
  }
});

test("module route guard decisions cover locked, hidden, unavailable, and owner paths", () => {
  const lockedBusiness = getModuleRouteDecision(
    noPermissions,
    "/approvals",
    navigationModuleRecords,
    [
      access({
        access_state: "locked",
        category: "business",
        locked: true,
        missing_permissions: ["reviews.read"],
        module_key: "business.approvals",
        route_namespace: "/approvals",
        status: "enabled",
      }),
    ],
  );
  const hiddenAdmin = getModuleRouteDecision(
    noPermissions,
    "/users",
    navigationModuleRecords,
    [
      access({
        access_state: "hidden",
        category: "admin",
        denied_behavior: "hide_when_denied",
        hidden: true,
        module_key: "admin.users",
        route_namespace: "/users",
        status: "sealed",
        visible: false,
      }),
    ],
  );
  const unavailableApprovals = getModuleRouteDecision(
    ownerPermissions,
    "/approvals",
    navigationModuleRecords,
    [
      access({
        access_state: "unavailable",
        category: "business",
        module_key: "business.approvals",
        route_namespace: "/approvals",
        status: "unavailable",
        unavailable: true,
      }),
    ],
  );
  const ownerUsers = getModuleRouteDecision(
    ownerPermissions,
    "/users",
    navigationModuleRecords,
    [
      access({
        access_state: "available",
        category: "admin",
        denied_behavior: "hide_when_denied",
        module_key: "admin.users",
        route_namespace: "/users",
        status: "sealed",
      }),
    ],
  );

  assert.equal(lockedBusiness.noticeType, "no_permission");
  assert.equal(lockedBusiness.canEnter, false);
  assert.equal(hiddenAdmin.noticeType, "no_permission");
  assert.equal(hiddenAdmin.canEnter, false);
  assert.equal(unavailableApprovals.noticeType, "module_unavailable");
  assert.equal(unavailableApprovals.canEnter, false);
  assert.equal(ownerUsers.noticeType, "none");
  assert.equal(ownerUsers.canEnter, true);
});

test("module notice copy remains module-aware", () => {
  assert.equal(MODULE_UNAVAILABLE_TITLE, "Product area unavailable");
  assert.match(MODULE_UNAVAILABLE_DESCRIPTION, /workspace/);
  assert.equal(MODULE_NO_PERMISSION_TITLE, "Access needed");
  assert.match(MODULE_NO_PERMISSION_DESCRIPTION, /product area/);
  assert.doesNotMatch(
    [
      MODULE_UNAVAILABLE_TITLE,
      MODULE_UNAVAILABLE_DESCRIPTION,
      MODULE_NO_PERMISSION_TITLE,
      MODULE_NO_PERMISSION_DESCRIPTION,
    ].join(" "),
    /secret|token|password|credential|api[_ -]?key|authorization|env|url/i,
  );
});

test("C05 and C06 regression assumptions remain intact", () => {
  const usersModule = item("admin.users");

  assert.equal(isOwnerFullAccess(ownerPermissions), true);
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
  assert.equal(canShowPermissionManagementEntry(ownerPermissions), true);
  assert.equal(
    canShowPermissionManagementEntry(permissionsReadPermissions),
    false,
  );
});

test("role defaults and super_admin do not become implicit module access", () => {
  const approvalsWithoutExplicitAssignment = getNavigationStateForModule(
    noPermissions,
    item("business.approvals"),
    [
      access({
        access_state: "locked",
        category: "business",
        locked: true,
        missing_permissions: ["reviews.read"],
        module_key: "business.approvals",
        route_namespace: "/approvals",
        status: "enabled",
      }),
    ],
  );
  const superAdminWithoutAssignments = getNavigationStateForModule(
    noPermissions,
    item("admin.users"),
    [
      access({
        access_state: "hidden",
        category: "admin",
        denied_behavior: "hide_when_denied",
        hidden: true,
        module_key: "admin.users",
        route_namespace: "/users",
        status: "sealed",
        visible: false,
      }),
    ],
  );

  assert.equal(approvalsWithoutExplicitAssignment.isLocked, true);
  assert.equal(superAdminWithoutAssignments.isHidden, true);
});

test("wildcard permission does not override module access safety states", () => {
  const wildcardHiddenUsers = getNavigationStateForModule(
    wildcardNonOwnerPermissions,
    item("admin.users"),
    [],
    { moduleAccessUnknown: true },
  );
  const backendLockedApprovals = getNavigationStateForModule(
    wildcardNonOwnerPermissions,
    item("business.approvals"),
    [
      access({
        access_state: "locked",
        category: "business",
        locked: true,
        missing_permissions: ["reviews.read"],
        module_key: "business.approvals",
        route_namespace: "/approvals",
        status: "enabled",
      }),
    ],
  );

  assert.equal(wildcardHiddenUsers.isHidden, true);
  assert.equal(wildcardHiddenUsers.canEnter, false);
  assert.equal(backendLockedApprovals.isLocked, true);
  assert.equal(backendLockedApprovals.canEnter, false);
});

test("sidebar navigation exposes only productized capability entries", () => {
  const moduleKeys = navigationItems.map((entry) => entry.module_key);

  assert.deepEqual(moduleKeys, [
    "admin.users",
    "admin.organizations",
    "admin.permissions",
    "system.operation_logs",
    "business.approvals",
  ]);
  for (const legacyKey of [
    "core.dashboard",
    "admin.modules",
    "admin.settings",
    "business.jobs",
    "business.products",
    "business.reviews",
    "experimental.foundation_demo",
    "integration.n8n_test_bridge",
  ]) {
    assert.equal(moduleKeys.includes(legacyKey), false);
  }
  assert.equal(moduleKeys.some((key) => key.startsWith("k01")), false);
  assert.equal(
    navigationItems.some((entry) => /P0[1-8]|K01|WooCommerce/i.test(entry.label)),
    false,
  );
  assert.equal(
    navigationModuleRecords.some((entry) =>
      /k01|product_knowledge|p0[1-8]|p_series|woocommerce|minio|filebrowser/i.test(
        `${entry.module_key} ${entry.label}`,
      ),
    ),
    false,
  );
});
