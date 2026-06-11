import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";
import {
  embeddedNavigationModules,
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

const modulesReadPermissions = {
  assignments: [
    {
      permission_key: "modules.read",
      scope_key: "*",
      scope_type: "global",
    },
  ],
  is_owner_full_access: false,
  permission_keys: ["modules.read"],
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
    category: "core",
    denied_behavior: "hide_when_denied",
    module_key: "core.dashboard",
    route_namespace: "/dashboard",
    status: "sealed",
  }),
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
    denied_behavior: "hide_when_denied",
    module_key: "admin.permissions",
    required_permissions: ["permissions.read"],
    route_namespace: "/users",
    status: "sealed",
  }),
  manifest({
    category: "admin",
    denied_behavior: "hide_when_denied",
    module_key: "admin.modules",
    required_permissions: ["modules.read"],
    route_namespace: "/modules",
    status: "sealed",
  }),
  manifest({
    category: "admin",
    denied_behavior: "hide_when_denied",
    module_key: "admin.agents",
    required_permissions: ["modules.read"],
    route_namespace: "/agents",
    status: "sealed",
  }),
  manifest({
    category: "admin",
    denied_behavior: "hide_when_denied",
    module_key: "admin.workflows",
    required_permissions: ["modules.read"],
    route_namespace: "/workflows",
    status: "sealed",
  }),
  manifest({
    category: "admin",
    denied_behavior: "hide_when_denied",
    module_key: "admin.settings",
    required_permissions: ["settings.read"],
    route_namespace: "/settings",
    status: "planned",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    module_key: "business.products",
    required_permissions: ["products.read"],
    route_namespace: "/products",
    status: "planned",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    module_key: "business.jobs",
    required_permissions: ["jobs.read"],
    route_namespace: "/jobs",
    status: "enabled",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    module_key: "business.artifacts",
    required_permissions: ["artifacts.read"],
    route_namespace: "/artifacts",
    status: "enabled",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    module_key: "business.reviews",
    required_permissions: ["reviews.read"],
    route_namespace: "/reviews",
    status: "enabled",
  }),
  manifest({
    category: "system",
    denied_behavior: "hide_when_denied",
    module_key: "system.errors",
    required_permissions: ["operation_logs.read"],
    route_namespace: "/errors",
    status: "enabled",
  }),
  manifest({
    category: "system",
    denied_behavior: "hide_when_denied",
    module_key: "system.memory_events",
    required_permissions: ["operation_logs.read"],
    route_namespace: "/memory-events",
    status: "enabled",
  }),
];

test("backend proxy precisely allows C07B module registry paths", () => {
  assert.equal(
    isAllowedBackendProxyPath("GET", ["modules", "registry"]),
    true,
  );
  assert.equal(isAllowedBackendProxyPath("GET", ["modules", "me"]), true);
  assert.equal(
    isAllowedBackendProxyPath("POST", ["modules", "registry"]),
    false,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["modules", "anything-else"]),
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
  const lockedJobs = getNavigationStateForModule(
    noPermissions,
    item("business.jobs"),
    [
      access({
        access_state: "locked",
        category: "business",
        locked: true,
        missing_permissions: ["jobs.read"],
        module_key: "business.jobs",
        route_namespace: "/jobs",
        status: "enabled",
      }),
    ],
  );

  assert.equal(isModuleVisible(ownerUsers), true);
  assert.equal(canEnterModuleRoute(ownerUsers), true);
  assert.equal(isModuleHidden(hiddenUsers), true);
  assert.equal(isAdminOrSystemModule(item("admin.users")), true);
  assert.equal(isModuleLocked(lockedJobs), true);
  assert.equal(isBusinessModule(item("business.jobs")), true);
});

test("planned and adapter_pending modules are unavailable and not enterable", () => {
  const plannedProducts = getNavigationStateForModule(
    ownerPermissions,
    item("business.products"),
    [
      access({
        access_state: "planned",
        category: "business",
        module_key: "business.products",
        route_namespace: "/products",
        status: "planned",
        unavailable: true,
      }),
    ],
  );
  const adapterPendingBridge = getNavigationStateForModule(
    ownerPermissions,
    item("integration.n8n_test_bridge"),
    [
      access({
        access_state: "adapter_pending",
        category: "integration",
        denied_behavior: "hide_when_denied",
        module_key: "integration.n8n_test_bridge",
        route_namespace: "/n8n-test",
        status: "adapter_pending",
        unavailable: true,
      }),
    ],
  );

  assert.equal(isModuleUnavailable(plannedProducts), true);
  assert.equal(plannedProducts.badge, "planned");
  assert.equal(canEnterModuleRoute(plannedProducts), false);
  assert.equal(isModuleUnavailable(adapterPendingBridge), true);
  assert.equal(adapterPendingBridge.badge, "adapter_pending");
  assert.equal(canEnterModuleRoute(adapterPendingBridge), false);
});

test("missing module access state safely degrades without exposing admin/system modules", () => {
  const adminModules = getNavigationStateForModule(
    modulesReadPermissions,
    item("admin.modules"),
    [],
    { moduleAccessUnknown: true },
  );
  const businessJobs = getNavigationStateForModule(
    noPermissions,
    item("business.jobs"),
    [],
    { moduleAccessUnknown: true },
  );

  assert.equal(adminModules.moduleAccessUnknown, true);
  assert.equal(adminModules.isVisible, false);
  assert.equal(adminModules.isHidden, true);
  assert.equal(businessJobs.isVisible, true);
  assert.equal(businessJobs.isLocked, true);
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
});

test("every navigation module is registered and aligned with registry metadata", () => {
  assert.equal(
    navigationModuleRecords.every(
      (record) => record.module_key || record.core_shell_exception,
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
          ...item("business.jobs"),
          module_key: "business.missing",
        },
      ],
      registryItems,
    ),
  );
});

test("admin.users and admin.permissions remain hidden for non-owner and visible for owner", () => {
  const adminUsers = item("admin.users");
  const adminPermissions = embeddedNavigationModules[0];

  assert.equal(adminUsers.owner_only, true);
  assert.equal(adminPermissions.module_key, "admin.permissions");
  assert.equal(adminPermissions.owner_only, true);

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

test("business.products stays locked for users without permission", () => {
  const productsState = getNavigationStateForModule(
    noPermissions,
    item("business.products"),
    [
      access({
        access_state: "locked",
        category: "business",
        locked: true,
        missing_permissions: ["products.read"],
        module_key: "business.products",
        route_namespace: "/products",
        status: "planned",
        unavailable: true,
      }),
    ],
  );

  assert.equal(productsState.isVisible, true);
  assert.equal(productsState.isLocked, true);
  assert.equal(productsState.badge, "locked");
});

test("module route guard decisions cover locked, hidden, unavailable, and owner paths", () => {
  const lockedBusiness = getModuleRouteDecision(
    noPermissions,
    "/jobs",
    navigationModuleRecords,
    [
      access({
        access_state: "locked",
        category: "business",
        locked: true,
        missing_permissions: ["jobs.read"],
        module_key: "business.jobs",
        route_namespace: "/jobs",
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
  const unavailableProducts = getModuleRouteDecision(
    ownerPermissions,
    "/products",
    navigationModuleRecords,
    [
      access({
        access_state: "planned",
        category: "business",
        module_key: "business.products",
        route_namespace: "/products",
        status: "planned",
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
  assert.equal(unavailableProducts.noticeType, "module_unavailable");
  assert.equal(unavailableProducts.canEnter, false);
  assert.equal(ownerUsers.noticeType, "none");
  assert.equal(ownerUsers.canEnter, true);
});

test("module notice copy remains module-aware", () => {
  assert.equal(MODULE_UNAVAILABLE_TITLE, "模块暂不可用");
  assert.match(MODULE_UNAVAILABLE_DESCRIPTION, /尚未接入执行能力/);
  assert.equal(MODULE_NO_PERMISSION_TITLE, "无权访问此模块");
  assert.match(MODULE_NO_PERMISSION_DESCRIPTION, /后端校验/);
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
  const jobsWithoutExplicitAssignment = getNavigationStateForModule(
    noPermissions,
    item("business.jobs"),
    [
      access({
        access_state: "locked",
        category: "business",
        locked: true,
        missing_permissions: ["jobs.read"],
        module_key: "business.jobs",
        route_namespace: "/jobs",
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

  assert.equal(jobsWithoutExplicitAssignment.isLocked, true);
  assert.equal(superAdminWithoutAssignments.isHidden, true);
});

test("sidebar navigation keeps C07B module keys and no K01 or P-series menus", () => {
  const moduleKeys = navigationItems.map((entry) => entry.module_key);

  assert.ok(moduleKeys.includes("core.dashboard"));
  assert.ok(moduleKeys.includes("admin.users"));
  assert.ok(moduleKeys.includes("business.jobs"));
  assert.equal(moduleKeys.some((key) => key.startsWith("k01")), false);
  assert.equal(
    navigationItems.some((entry) => /P0[1-8]|K01|WooCommerce/i.test(entry.label)),
    false,
  );
});
