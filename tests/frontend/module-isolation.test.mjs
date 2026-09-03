import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";
import {
  navigationItems,
  navigationModuleRecords,
  pageTitles,
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
    required_permissions: ["modules.read"],
    route_namespace: "/foundation-demo",
    status: "enabled",
  }),
  manifest({
    category: "integration",
    denied_behavior: "hide_when_denied",
    external_dependencies: ["n8n"],
    module_key: "integration.n8n_test_bridge",
    required_permissions: ["modules.read"],
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
    route_namespace: "/permissions",
    status: "sealed",
  }),
  manifest({
    category: "admin",
    denied_behavior: "hide_when_denied",
    module_key: "admin.organizations",
    required_permissions: ["users.manage"],
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
    category: "business",
    denied_behavior: "show_locked",
    module_key: "business.reviews",
    required_permissions: ["reviews.read"],
    route_namespace: "/reviews",
    status: "enabled",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: [
      "serp",
      "chatgpt",
      "claude_opus",
      "deepseek",
      "ai_provider",
      "n8n",
    ],
    module_key: "k.product_knowledge",
    required_permissions: ["products.read"],
    route_namespace: "/products",
    status: "active",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: ["deepseek", "ai_provider"],
    module_key: "i.image_system",
    required_permissions: ["i.image_system.read"],
    route_namespace: "/image-system",
    status: "active",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: ["n8n", "woocommerce"],
    module_key: "p.upload",
    required_permissions: ["p.upload.read"],
    route_namespace: "/p-upload",
    status: "active",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: ["keepa", "deepseek", "ai_provider"],
    module_key: "r.warehouse",
    route_namespace: "/r-w",
    status: "active",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: ["serper", "deepseek", "ai_provider"],
    module_key: "r.analysis",
    route_namespace: "/r-a",
    status: "active",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: ["serper", "alibaba1688"],
    module_key: "f.enrichment",
    required_permissions: ["f.enrichment.read"],
    route_namespace: "/f-enrichment",
    status: "active",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: [],
    module_key: "h.site_health",
    required_permissions: ["h.site_health.read"],
    route_namespace: "/h-site-health",
    status: "active",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: [],
    module_key: "b2b.wholesale",
    required_permissions: ["b2b.wholesale.read"],
    route_namespace: "/b2b-wholesale",
    status: "active",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: [],
    module_key: "mfg.inventory",
    required_permissions: ["mfg.inventory.read"],
    route_namespace: "/mfg-inventory",
    status: "active",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: [],
    module_key: "geo.content",
    required_permissions: ["geo.content.read"],
    route_namespace: "/geo",
    status: "active",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: [],
    module_key: "seo.content",
    required_permissions: ["seo.content.read"],
    route_namespace: "/seo",
    status: "active",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: [],
    module_key: "content.desk",
    required_permissions: ["content.desk.read"],
    route_namespace: "/content-desk",
    status: "active",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: ["track17"],
    module_key: "w.site_ops",
    required_permissions: ["w.site_ops.read"],
    route_namespace: "/w-s",
    status: "active",
  }),
  manifest({
    category: "business",
    denied_behavior: "show_locked",
    external_dependencies: [],
    module_key: "cs.customer_service",
    required_permissions: ["cs.customer_service.read"],
    route_namespace: "/cs/customer-service",
    status: "active",
  }),
  manifest({
    category: "core",
    denied_behavior: "hide_when_denied",
    module_key: "core.dashboard",
    route_namespace: "/dashboard",
    status: "sealed",
  }),
  manifest({
    category: "core",
    denied_behavior: "hide_when_denied",
    module_key: "core.vpn",
    route_namespace: "/vpn",
    status: "sealed",
  }),
  manifest({
    category: "admin",
    denied_behavior: "hide_when_denied",
    module_key: "admin.modules",
    required_permissions: ["modules.read"],
    route_namespace: "/module-control",
    status: "sealed",
  }),
  manifest({
    category: "admin",
    denied_behavior: "hide_when_denied",
    module_key: "admin.key_management",
    required_permissions: ["modules.read"],
    route_namespace: "/api-key-management",
    status: "sealed",
  }),
  manifest({
    category: "admin",
    denied_behavior: "hide_when_denied",
    module_key: "admin.mcp_keys",
    required_permissions: ["modules.read"],
    route_namespace: "/mcp-keys",
    status: "sealed",
  }),
  manifest({
    category: "admin",
    denied_behavior: "hide_when_denied",
    module_key: "admin.key_health",
    required_permissions: ["modules.read"],
    route_namespace: "/key-health",
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
  manifest({
    category: "system",
    denied_behavior: "hide_when_denied",
    module_key: "system.operation_logs",
    required_permissions: ["operation_logs.read"],
    route_namespace: "/operation-logs",
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
    isAllowedBackendProxyPath("POST", ["i", "images", "generate"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("POST", ["i", "images", "edit"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["i", "media-library"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["r", "commerce", "skills"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["r", "commerce", "report"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("POST", ["r", "commerce", "run"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("POST", ["r", "commerce", "review"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("DELETE", ["r", "commerce", "review"]),
    false,
  );
  assert.equal(
    isAllowedBackendProxyPath("POST", [
      "k",
      "products",
      "123e4567-e89b-12d3-a456-426614174000",
      "images",
      "import-i-output",
    ]),
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
  const healthId = "123e4567-e89b-12d3-a456-426614174000";
  assert.equal(isAllowedBackendProxyPath("GET", ["h", "runs"]), true);
  assert.equal(isAllowedBackendProxyPath("POST", ["h", "runs"]), false);
  assert.equal(
    isAllowedBackendProxyPath("GET", ["h", "runs", healthId]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("POST", ["h", "runs", "trigger"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["h", "runs", "trigger"]),
    false,
  );
  assert.equal(isAllowedBackendProxyPath("GET", ["h", "findings"]), true);
  assert.equal(
    isAllowedBackendProxyPath("PATCH", ["h", "findings", healthId]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["h", "findings", healthId]),
    false,
  );
  assert.equal(isAllowedBackendProxyPath("POST", ["h", "ingest"]), false);
  assert.equal(
    isAllowedBackendProxyPath("POST", ["modules", "registry"]),
    false,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["modules", "anything-else"]),
    true,
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

test("frontend capability graph contains owner bypass for locked and hidden states", () => {
  const capabilitySource = readFileSync(
    "frontend/src/lib/frontend-capability-state.ts",
    "utf8",
  );

  assert.match(capabilitySource, /function ownerCapabilityItem/);
  assert.match(capabilitySource, /can_enter: routeBound && state !== "hidden"/);
  assert.match(
    capabilitySource,
    /navigationState\.isHidden[\s\S]*navigationState\.isLocked[\s\S]*adapterAccess\?\.hidden[\s\S]*adapterAccess\?\.locked/,
  );
  assert.match(
    capabilitySource,
    /is_owner_full_access: owner[\s\S]*permissions: owner \? \["\*"\] : \[\]/,
  );
});

test("sidebar keeps C system modules at root and organizations as secondary layer", () => {
  const sidebarSource = readFileSync(
    "frontend/src/components/capability-sidebar-engine.tsx",
    "utf8",
  );

  assert.match(sidebarSource, /const C_SYSTEM_MODULE_ORDER = \[/);
  assert.match(
    sidebarSource,
    /admin\.modules[\s\S]*admin\.key_health[\s\S]*admin\.permissions[\s\S]*admin\.users[\s\S]*core\.dashboard[\s\S]*core\.vpn/,
  );
  assert.doesNotMatch(sidebarSource, /admin\.key_management/);
  assert.match(sidebarSource, /const C_SYSTEM_MODULE_KEYS: ReadonlySet<string> = new Set/);
  assert.match(sidebarSource, /C_SYSTEM_MODULE_KEYS\.has\(moduleId\)/);
  assert.match(
    sidebarSource,
    /ORGANIZATION_MODULE_PREFIXES = \[\s*"r\.",\s*"k\.",\s*"i\.",\s*"p\.",\s*"f\.",\s*"h\.",\s*"w\.",\s*"cs\.",\s*"b2b\.",\s*"geo\.",\s*"seo\.",\s*"gmc\.",\s*"content\.",\s*"mfg\.",?\s*\]/,
  );
  // 「哪些模块只属于国际贸易组织」不再由前端判定。
  // 这里原本断言前端有一组 normalized.startsWith("i."/"w."/"f."/"h."/"cs.") 判据，
  // 配合一个按**组织中文名**比对的 isProductKnowledgeOrg 来遮蔽模块。那是第二套
  // 真相源：后端 INTL_TRADE_ONLY_MODULE_KEYS 漏了 k./i./p. 时只在前端被遮住，
  // 敲 URL 照样进（实测制造超管能打开 K 的创建表单）；而且改一次组织名整套失效。
  // 2026-08-31 收敛到后端，这里改为断言那套遮罩**不会回来**。
  assert.doesNotMatch(sidebarSource, /isRestrictedProductModule/);
  assert.doesNotMatch(sidebarSource, /isProductKnowledgeOrg/);
  assert.doesNotMatch(sidebarSource, /涌龙麟（深圳）国际贸易有限公司/);
  assert.match(sidebarSource, /function capabilitySidebarVisible/);
  assert.match(sidebarSource, /return capabilitySidebarVisible\(fallbackItem\);/);
  assert.match(sidebarSource, /return capabilitySidebarVisible\(item\);/);
  assert.doesNotMatch(sidebarSource, /moduleAccessReady/);
  assert.doesNotMatch(sidebarSource, /item\?\.can_enter\s*&&/);
  assert.match(sidebarSource, /<span className="navigation-label">C系统<\/span>/);
  assert.match(sidebarSource, /className="navigation-divider"/);
  assert.match(sidebarSource, /<span className="navigation-label">组织<\/span>/);
  assert.match(sidebarSource, /暂无组织/);
  assert.match(sidebarSource, /暂无模块/);
  assert.match(sidebarSource, /runtimeOrganizations = useMemo/);
  assert.match(sidebarSource, /const organizations = runtimeOrganizations/);
  assert.doesNotMatch(sidebarSource, /TARGET_ORGANIZATION_NAME/);
  assert.doesNotMatch(sidebarSource, /OWNER_ORG_MODULE_ORDER/);
  assert.doesNotMatch(sidebarSource, /<span className="navigation-label">Organizations<\/span>/);
});

test("sidebar suppresses no-execution badge copy", () => {
  const sidebarSource = readFileSync(
    "frontend/src/components/capability-sidebar-engine.tsx",
    "utf8",
  );

  assert.match(sidebarSource, /visibleBadge = badge === "no_execution" \? null : badge/);
  assert.match(sidebarSource, /CAPABILITY_BADGE_LABELS\[visibleBadge\]/);
});

test("I image system keeps UI copy localized and uses placeholders for style hints", () => {
  const workspaceSource = readFileSync(
    "frontend/src/modules/i/image-system/ImageSystemWorkspace.tsx",
    "utf8",
  );

  assert.match(workspaceSource, /生成提示词/);
  assert.match(workspaceSource, /编辑提示词/);
  assert.match(workspaceSource, /已安装 \{PROMPT_SKILL_LABEL\}/);
  assert.match(workspaceSource, /DeepSeek V4 Pro 转换成英文作图指令/);
  assert.match(workspaceSource, /label: "风格"/);
  assert.match(workspaceSource, /label: "光线"/);
  assert.match(workspaceSource, /label: "构图"/);
  assert.match(workspaceSource, /label: "背景"/);
  assert.match(workspaceSource, /placeholder=\{field\.generatePlaceholder\}/);
  assert.match(workspaceSource, /placeholder=\{field\.editPlaceholder\}/);
  assert.match(workspaceSource, /function ProgressBar/);
  assert.match(workspaceSource, /DeepSeek 正在优化英文作图指令/);
  assert.match(workspaceSource, /gpt-image-2 正在生成图片/);
  assert.match(workspaceSource, /上传临时参考图并调用 gpt-image-2/);
  assert.match(workspaceSource, /function normalizeAspectRatio/);
  assert.match(workspaceSource, /const DEFAULT_ASPECT_RATIO = "1:1"/);
  assert.match(workspaceSource, /const DEFAULT_GENERATION_COUNT = 1/);
  assert.match(workspaceSource, /placeholder="默认比例：1:1"/);
  assert.match(workspaceSource, /placeholder="默认图片数量：1张"/);
  assert.match(workspaceSource, /aria-label="放大查看图片"/);
  assert.match(workspaceSource, /aria-label="图片放大预览"/);
  assert.match(workspaceSource, /移除这张/);
  assert.match(workspaceSource, /setGeneratePrompt\(""\)/);
  assert.match(workspaceSource, /function MediaLibraryPreview/);
  assert.match(workspaceSource, /aria-label="媒体库图片放大预览"/);
  assert.match(workspaceSource, /aria-label="放大查看媒体库图片"/);
  assert.match(workspaceSource, /删除这张/);
  assert.match(workspaceSource, /setEditPrompt\(""\)/);
  assert.match(workspaceSource, /setEditFiles\(\[\]\)/);
  assert.doesNotMatch(workspaceSource, /<span>Prompt<\/span>/);
  assert.doesNotMatch(workspaceSource, /<span>\{key\}<\/span>/);
});

test("productized routes are visible while diagnostics stay out of navigation", () => {
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

  assert.equal(isModuleUnavailable(unavailableApprovals), false);
  assert.equal(unavailableApprovals.badge, null);
  assert.equal(canEnterModuleRoute(unavailableApprovals), true);
  assert.equal(item("experimental.foundation_demo"), undefined);
  assert.equal(item("integration.n8n_test_bridge"), undefined);
  assert.equal(item("business.products"), undefined);
  assert.equal(item("business.artifacts"), undefined);
  assert.equal(item("business.jobs"), undefined);
  assert.equal(item("admin.workflows"), undefined);
  assert.equal(item("core.dashboard").href, "/dashboard");
  assert.equal(item("core.vpn").href, "/vpn");
  // M15 (QA 2026-08-22) removed the "设置" nav entry (dead link); the page
  // title stays so the route still renders a name when reached directly.
  assert.equal(item("admin.settings"), undefined);
  assert.equal(pageTitles["/settings"], "设置");
});

test("VPN route uses its dedicated cockpit inside the normal login guard", () => {
  const vpnRouteSource = readFileSync(
    "frontend/src/app/(console)/vpn/page.tsx",
    "utf8",
  );

  assert.match(vpnRouteSource, /DashboardAccessControl/);
  assert.match(vpnRouteSource, /VpnDashboard/);
  assert.doesNotMatch(vpnRouteSource, /OperationsDashboard/);
  assert.match(
    vpnRouteSource,
    /<DashboardAccessControl>[\s\S]*<VpnDashboard \/>[\s\S]*<\/DashboardAccessControl>/,
  );
  assert.doesNotMatch(vpnRouteSource, /className=|style=|globals\.css/);
});

test("owner full access bypasses unavailable route guard decisions", () => {
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

  assert.equal(isModuleUnavailable(unavailableApprovals), false);
  assert.equal(unavailableApprovals.badge, null);
  assert.equal(canEnterModuleRoute(unavailableApprovals), true);
  assert.equal(unavailableDecision.noticeType, "none");
  assert.equal(unavailableDecision.canEnter, true);
});

test("missing module access state safely degrades without hiding entries", () => {
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
  assert.equal(adminOrganizations.isVisible, true);
  assert.equal(adminOrganizations.isLocked, false);
  assert.equal(adminOrganizations.canEnter, true);
  assert.equal(systemLogs.isVisible, true);
  assert.equal(systemLogs.isHidden, false);
  assert.equal(businessApprovals.isVisible, true);
  assert.equal(businessApprovals.isLocked, true);
});

test("/modules/me failure fallback keeps non-owner entries locked", () => {
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

  assert.equal(missingUsers.accessState, "unknown");
  assert.equal(missingUsers.isHidden, false);
  assert.equal(missingUsers.isLocked, false);
  assert.equal(missingUsers.noticeType, "none");
  assert.equal(missingLogs.accessState, "unknown");
  assert.equal(missingLogs.isHidden, true);
  assert.equal(missingLogs.isLocked, false);
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

test("admin.users stays visible and admin.permissions follows read permission visibility", () => {
  const adminUsers = item("admin.users");
  const adminPermissions = item("admin.permissions");

  assert.equal(adminUsers.label, "用户管理");
  assert.equal(adminUsers.module_key, "admin.users");
  assert.equal(adminUsers.owner_only, undefined);
  assert.equal(adminUsers.required_permission, undefined);
  assert.equal(adminUsers.denied_behavior, "hide_when_denied");
  assert.equal(adminUsers.category, "admin");
  assert.equal(adminPermissions.label, "权限管理");
  assert.equal(adminPermissions.module_key, "admin.permissions");
  assert.equal(adminPermissions.owner_only, undefined);
  assert.equal(adminPermissions.denied_behavior, "hide_when_denied");
  assert.equal(adminPermissions.category, "admin");

  assert.equal(
    getNavigationStateForModule(noPermissions, adminUsers, [], {
      moduleAccessUnknown: true,
    }).isVisible,
    true,
  );
  assert.equal(
    getNavigationStateForModule(
      noPermissions,
      adminPermissions,
      [],
      { moduleAccessUnknown: true },
    ).isVisible,
    false,
  );
  assert.equal(
    getNavigationStateForModule(
      permissionsReadPermissions,
      adminPermissions,
      [],
      { moduleAccessUnknown: true },
    ).isVisible,
    true,
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

test("admin.organizations is visible and enterable for authenticated users", () => {
  const adminOrganizations = item("admin.organizations");
  const state = getNavigationStateForModule(
    noPermissions,
    adminOrganizations,
    [],
    { moduleAccessUnknown: true },
  );

  assert.equal(adminOrganizations.label, "组织管理");
  assert.equal(adminOrganizations.module_key, "admin.organizations");
  assert.equal(adminOrganizations.owner_only, undefined);
  assert.equal(adminOrganizations.required_permission, undefined);
  assert.equal(adminOrganizations.denied_behavior, "hide_when_denied");
  assert.equal(adminOrganizations.category, "admin");
  assert.equal(state.isVisible, true);
  assert.equal(state.isLocked, false);
  assert.equal(state.canEnter, true);
});

test("organization page keeps only create and list sections", () => {
  const source = readFileSync(
    "frontend/src/components/organization-product-view.tsx",
    "utf8",
  );
  const headings = source.match(/<h3 /g) ?? [];

  assert.equal(headings.length, 2);
  assert.match(source, /创建组织/);
  assert.match(source, /组织列表/);
  assert.match(source, /isOwner \? \(/);
  assert.doesNotMatch(
    source,
    /Lifecycle actions|Member actions|Organization detail/,
  );
  assert.doesNotMatch(
    source,
    /capability-summary-grid|product-console-grid|ops-dashboard-grid/,
  );
  assert.doesNotMatch(source, /<select|Owner user ID|metadata:/);
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

test("permission-gated admin entries and system logs stay hidden when access is unknown", () => {
  const usersState = getNavigationStateForModule(
    noPermissions,
    item("admin.users"),
    [],
    { moduleAccessUnknown: true },
  );
  assert.equal(usersState.isVisible, true);
  assert.equal(usersState.isHidden, false);
  assert.equal(usersState.isLocked, false);
  assert.equal(usersState.canEnter, true);

  for (const moduleKey of ["admin.permissions", "system.operation_logs"]) {
    const state = getNavigationStateForModule(
      noPermissions,
      item(moduleKey),
      [],
      { moduleAccessUnknown: true },
    );
    assert.equal(state.isVisible, false);
    assert.equal(state.isHidden, true);
    assert.equal(state.isLocked, false);
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
  assert.equal(unavailableApprovals.noticeType, "none");
  assert.equal(unavailableApprovals.canEnter, true);
  assert.equal(ownerUsers.noticeType, "none");
  assert.equal(ownerUsers.canEnter, true);
});

test("module notice copy remains module-aware", () => {
  assert.equal(MODULE_UNAVAILABLE_TITLE, "功能区暂不可用");
  assert.match(MODULE_UNAVAILABLE_DESCRIPTION, /功能区/);
  assert.equal(MODULE_NO_PERMISSION_TITLE, "无权访问");
  assert.match(MODULE_NO_PERMISSION_DESCRIPTION, /功能区/);
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
    canAccess: true,
    isLocked: false,
    isVisible: true,
  });
  assert.deepEqual(
    getPermissionAccessState(usersManagePermissions, usersModule),
    {
      canAccess: true,
      isLocked: false,
      isVisible: true,
    },
  );
  assert.equal(canShowPermissionManagementEntry(ownerPermissions), true);
  assert.equal(
    canShowPermissionManagementEntry(permissionsReadPermissions),
    false,
  );
});

test("backend locked and hidden access states remain authoritative in route helpers", () => {
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
  const wildcardLockedUsers = getNavigationStateForModule(
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

  assert.equal(wildcardLockedUsers.isVisible, true);
  assert.equal(wildcardLockedUsers.isHidden, false);
  assert.equal(wildcardLockedUsers.isLocked, false);
  assert.equal(wildcardLockedUsers.canEnter, true);
  assert.equal(backendLockedApprovals.isLocked, true);
  assert.equal(backendLockedApprovals.canEnter, false);
});

test("K product knowledge page uses action-scoped execution gate in capability graph", () => {
  const capabilitySource = readFileSync(
    "frontend/src/lib/frontend-capability-state.ts",
    "utf8",
  );

  assert.match(
    capabilitySource,
    /K_PRODUCT_KNOWLEDGE_MODULE_KEY = "k\.product_knowledge"/,
  );
  assert.match(capabilitySource, /function usesActionScopedExecutionGate/);
  assert.match(
    capabilitySource,
    /usesActionScopedExecutionGate\(manifest\?\.module_key \?\? adapter\?\.module_key\)/,
  );
});

test("API key management stays consolidated inside module control", () => {
  const navigationSource = readFileSync(
    "frontend/src/lib/navigation.ts",
    "utf8",
  );
  const sidebarSource = readFileSync(
    "frontend/src/components/capability-sidebar-engine.tsx",
    "utf8",
  );
  const capabilitySource = readFileSync(
    "frontend/src/lib/frontend-capability-state.ts",
    "utf8",
  );
  const legacyRouteSource = readFileSync(
    "frontend/src/app/(console)/api-key-management/page.tsx",
    "utf8",
  );

  assert.doesNotMatch(navigationSource, /admin\.key_management/);
  assert.doesNotMatch(sidebarSource, /admin\.key_management/);
  assert.match(
    capabilitySource,
    /PRODUCT_HIDDEN_MODULE_KEYS = new Set\(\[[\s\S]*"admin\.key_management"/,
  );
  assert.match(legacyRouteSource, /redirect\("\/module-control"\)/);
  assert.doesNotMatch(legacyRouteSource, /ModuleRegistryProductView/);
});

test("legacy W-A route redirects to the W-S logistics hub", () => {
  const legacyRouteSource = readFileSync(
    "frontend/src/app/(console)/w-a/page.tsx",
    "utf8",
  );

  assert.match(legacyRouteSource, /redirect\("\/w-s"\)/);
  assert.doesNotMatch(legacyRouteSource, /ShippingDeck/);
});

test("sidebar navigation exposes the full productized capability structure", () => {
  const moduleKeys = navigationItems.map((entry) => entry.module_key);

  assert.deepEqual(moduleKeys, [
    "admin.users",
    // 「接入钥匙」(MCP 个人钥匙总览)。2026-08-28 上生产时漏加进这份期望清单，
    // 于是这条测试从那时起一直是红的——而 Docker 构建闸门因为 cd .. 的 bug
    // 跑了 0 条测试，红测试就这么被放行了。两个问题在 2026-08-31 一起修。
    "admin.mcp_keys",
    "admin.organizations",
    "admin.permissions",
    "k.product_knowledge",
    "i.image_system",
    "p.upload",
    "r.warehouse",
    "r.analysis",
    "f.enrichment",
    "h.site_health",
    "b2b.wholesale",
    "mfg.inventory",
    "content.desk",
    "geo.content",
    "seo.content",
    "w.site_ops",
    "cs.customer_service",
    "business.approvals",
    "business.reviews",
    "core.dashboard",
    "core.vpn",
    "admin.modules",
    "admin.key_health",
    "system.errors",
    "system.memory_events",
    "system.operation_logs",
    "admin.agents",
  ]);
  for (const legacyKey of [
    "experimental.foundation_demo",
    "integration.n8n_test_bridge",
  ]) {
    assert.equal(moduleKeys.includes(legacyKey), false);
  }
  const productKnowledge = item("k.product_knowledge");
  assert.equal(productKnowledge.label, "产品知识库");
  assert.equal(productKnowledge.href, "/products");
  assert.equal(productKnowledge.required_permission, "products.read");
  assert.equal(productKnowledge.denied_behavior, "show_locked");
  assert.equal(productKnowledge.category, "business");
  const imageSystem = item("i.image_system");
  assert.equal(imageSystem.label, "I系列图片系统");
  assert.equal(imageSystem.href, "/image-system");
  assert.equal(imageSystem.required_permission, "i.image_system.read");
  assert.equal(imageSystem.denied_behavior, "show_locked");
  assert.equal(imageSystem.category, "business");
  const siteHealth = item("h.site_health");
  assert.equal(siteHealth.label, "H 站点健康");
  assert.equal(siteHealth.href, "/h-site-health");
  assert.equal(siteHealth.route_namespace, "/h-site-health");
  assert.equal(siteHealth.required_permission, "h.site_health.read");
  const logisticsHub = item("w.site_ops");
  assert.equal(logisticsHub.label, "W-S 物流网络中枢");
  assert.equal(logisticsHub.href, "/w-s");
  assert.equal(logisticsHub.route_namespace, "/w-s");
  assert.equal(logisticsHub.required_permission, "w.site_ops.read");
  const customerService = item("cs.customer_service");
  assert.equal(customerService.label, "客服中心");
  assert.equal(customerService.href, "/cs/customer-service");
  assert.equal(customerService.route_namespace, "/cs/customer-service");
  assert.equal(
    customerService.required_permission,
    "cs.customer_service.read",
  );
  const moduleControl = item("admin.modules");
  assert.equal(moduleControl.label, "模块控制");
  assert.equal(moduleControl.href, "/module-control");
  assert.equal(moduleControl.route_namespace, "/module-control");
  const keyHealth = item("admin.key_health");
  assert.equal(keyHealth.label, "密钥检测");
  assert.equal(keyHealth.href, "/key-health");
  assert.equal(keyHealth.owner_only, true);
  assert.equal(keyHealth.required_permission, "modules.read");
  assert.equal(moduleKeys.some((key) => key.startsWith("k01")), false);
  assert.equal(
    navigationItems.some((entry) => /P0[1-8]|K01|WooCommerce/i.test(entry.label)),
    false,
  );
  assert.equal(
    navigationModuleRecords.some((entry) =>
      /k01|p0[1-8]|p_series|woocommerce|minio|filebrowser/i.test(
        `${entry.module_key} ${entry.label}`,
      ),
    ),
    false,
  );
});
