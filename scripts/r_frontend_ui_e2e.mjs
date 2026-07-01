import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const baseUrl = process.env.R_FRONTEND_BASE_URL || "http://127.0.0.1:3200";
const reportPath = path.resolve(
  process.cwd(),
  "reports/rw_sidebar_route_fix_report.json",
);
const fullRebuildReportPath = path.resolve(
  process.cwd(),
  "reports/frontend_full_rebuild_report.json",
);
const targetOrg = "涌龙麟（深圳）国际贸易有限公司";
const now = "2026-07-01T00:00:00.000Z";

function manifest({
  apiNamespace,
  displayName,
  icon,
  moduleKey,
  noApi = false,
  routeNamespace,
  status,
}) {
  return {
    allowed_scope_types: ["global", "organization", "module"],
    api_namespace: apiNamespace,
    audit_log_actions: [],
    category: "business",
    denied_behavior: "show_locked",
    description: displayName,
    docs_path: "r_system_v2/docs/ARCHITECTURE.md",
    execution_provider_required: false,
    external_dependencies: [],
    feature_flag_key: null,
    lifecycle: status === "active" ? "production_released" : "designed",
    module_adapter_required: false,
    module_key: moduleKey,
    navigation: {
      default_visible: true,
      group: "Registry",
      icon,
      label: displayName,
      order: moduleKey === "r.warehouse" ? 11 : 12,
      owner_only: false,
    },
    no_api: noApi,
    permission_manifest: [],
    production_release_required: moduleKey === "r.warehouse",
    required_permissions: [],
    route_namespace: routeNamespace,
    sandbox_required: false,
    staging_acceptance_required: moduleKey === "r.warehouse",
    status,
    unavailable_behavior: status === "disabled" ? "disabled" : "show_unavailable",
  };
}

function accessState({ moduleKey, routeNamespace, status }) {
  const unavailable = status === "disabled";
  return {
    access_state: unavailable ? "unavailable" : "available",
    category: "business",
    denied_behavior: "show_locked",
    executable: false,
    hidden: false,
    locked: false,
    missing_permissions: [],
    module_key: moduleKey,
    reason: unavailable ? "Module status is disabled." : "Module metadata is available.",
    required_permissions: [],
    route_namespace: routeNamespace,
    status,
    unavailable,
    visible: true,
  };
}

function moduleControlState({ displayName, enabled, moduleId }) {
  return {
    category: "business",
    display_name: displayName,
    enabled,
    error: {
      code: null,
      message: null,
      timestamp: null,
    },
    last_error_at: null,
    module_id: moduleId,
    org_id: "org_yll",
    runtime_error_code: null,
    runtime_error_message: null,
    runtime_status: enabled ? "active" : "disabled",
    status: enabled ? "active" : "disabled",
    updated_at: now,
  };
}

function bootstrapPayload({ includeTargetOrg }) {
  const rwManifest = manifest({
    apiNamespace: "/rw",
    displayName: "R-W 产品数据仓库",
    icon: "Database",
    moduleKey: "r.warehouse",
    routeNamespace: "/r-w",
    status: "active",
  });
  const raManifest = manifest({
    apiNamespace: "no_api",
    displayName: "R-A 产品分析中心",
    icon: "ClipboardCheck",
    moduleKey: "r.analysis",
    noApi: true,
    routeNamespace: "/r-a",
    status: "disabled",
  });
  const manifests = includeTargetOrg ? [rwManifest, raManifest] : [];
  const accessItems = includeTargetOrg
    ? [
        accessState({
          moduleKey: "r.warehouse",
          routeNamespace: "/r-w",
          status: "active",
        }),
        accessState({
          moduleKey: "r.analysis",
          routeNamespace: "/r-a",
          status: "disabled",
        }),
      ]
    : [];
  const organizations = includeTargetOrg
    ? [
        {
          modules: [
            moduleControlState({
              displayName: "R-W 产品数据仓库",
              enabled: true,
              moduleId: "r.warehouse",
            }),
            moduleControlState({
              displayName: "R-A 产品分析中心",
              enabled: false,
              moduleId: "r.analysis",
            }),
          ],
          org_id: "org_yll",
          org_name: targetOrg,
        },
      ]
    : [
        {
          modules: [],
          org_id: "org_other",
          org_name: "其他组织",
        },
      ];

  return {
    execution_providers_me: {
      data: { count: 0, is_owner_full_access: true, items: [], role: "owner", user_id: 1 },
      ok: true,
      status: 200,
    },
    execution_providers_registry: {
      data: { count: 0, items: [] },
      ok: true,
      status: 200,
    },
    live_gate_policies: {
      data: [],
      ok: true,
      status: 200,
    },
    live_gate_production_readiness: {
      data: {
        production_ready: true,
        readiness_passed: true,
      },
      ok: true,
      status: 200,
    },
    live_gate_readiness: {
      data: {
        readiness_passed: true,
      },
      ok: true,
      status: 200,
    },
    module_adapters_me: {
      data: { count: 0, is_owner_full_access: true, items: [], role: "owner", user_id: 1 },
      ok: true,
      status: 200,
    },
    module_adapters_registry: {
      data: { count: 0, items: [] },
      ok: true,
      status: 200,
    },
    module_control_center: {
      data: {
        auto_registered_count: 0,
        module_count: organizations.reduce(
          (count, organization) => count + organization.modules.length,
          0,
        ),
        organization_count: organizations.length,
        organizations,
      },
      ok: true,
      status: 200,
    },
    modules_me: {
      data: {
        count: accessItems.length,
        is_owner_full_access: true,
        items: accessItems,
        role: "owner",
        user_id: 1,
      },
      ok: true,
      status: 200,
    },
    modules_registry: {
      data: {
        count: manifests.length,
        items: manifests,
      },
      ok: true,
      status: 200,
    },
  };
}

async function installAuthAndBootstrap(page, { includeTargetOrg, tracker = null }) {
  const user = {
    id: 1,
    is_active: true,
    last_login_at: now,
    must_change_password: false,
    organization_id: includeTargetOrg ? "org_yll" : "org_other",
    role: "owner",
    username: "r-ui-e2e",
  };

  await page.addInitScript((storedUser) => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    if ("caches" in window) {
      window.caches
        .keys()
        .then((keys) => Promise.all(keys.map((key) => window.caches.delete(key))))
        .catch(() => {});
    }
    window.__BARONG_RUNTIME_CACHE_CLEARED__ = true;
    window.localStorage.setItem(
      "barong-auth-session",
      JSON.stringify({
        authComplete: true,
        sessionToken: "r-ui-e2e-token",
        user: storedUser,
      }),
    );
  }, user);

  await page.route("**/api/backend/auth/me", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(user),
    });
  });

  await page.route("**/api/backend/capability/bootstrap**", async (route) => {
    const payload = bootstrapPayload({ includeTargetOrg });
    if (tracker) {
      tracker.capability_bootstrap_api_hit = true;
      tracker.module_registry_source = "backend_api:/api/backend/capability/bootstrap";
      tracker.backend_module_keys = (
        payload.modules_registry.data.items ?? []
      ).map((item) => item.module_key);
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });
}

async function textVisible(page, text) {
  try {
    await page.getByText(text, { exact: false }).first().waitFor({
      state: "visible",
      timeout: 10_000,
    });
  } catch (error) {
    const bodyText = await page.locator("body").innerText().catch(() => "");
    throw new Error(
      `Expected text not visible: ${text}\nURL: ${page.url()}\nBody: ${bodyText.slice(
        0,
        1200,
      )}`,
      { cause: error },
    );
  }
  return true;
}

async function run() {
  const browser = await chromium.launch({ headless: true });
  const results = {
    cache_cleared: process.env.R_FRONTEND_CACHE_CLEARED === "true",
    mock_data_loaded: false,
    module_registry_source: "not_loaded",
    next_build_success: process.env.FRONTEND_NEXT_BUILD_SUCCESS === "true",
    organization_binding_status: "failed",
    organization_filter_passed: false,
    r_a_disabled_visible: false,
    ra_loaded_from_backend: false,
    route_r_a_accessible: false,
    route_r_w_accessible: false,
    runtime_storage_clean: false,
    rw_loaded_from_backend: false,
    route_status: {},
    sidebar_modules_loaded_from_backend: false,
    sidebar_r_a_visible: false,
    sidebar_r_w_visible: false,
    sidebar_status: "failed",
  };

  try {
    const targetPage = await browser.newPage();
    const targetTracker = {
      backend_module_keys: [],
      capability_bootstrap_api_hit: false,
      module_registry_source: "not_loaded",
    };
    await installAuthAndBootstrap(targetPage, {
      includeTargetOrg: true,
      tracker: targetTracker,
    });

    await targetPage.goto(`${baseUrl}/r-w/dashboard`, {
      waitUntil: "networkidle",
    });
    await textVisible(targetPage, "R-W 产品数据仓库");
    await textVisible(targetPage, targetOrg);
    await textVisible(targetPage, "Portable Door Draft Stopper");

    const rwSidebarVisible = await targetPage
      .locator(".navigation-tree-link", { hasText: "R-W 产品数据仓库" })
      .first()
      .isVisible();
    const raSidebar = targetPage
      .locator(".navigation-tree-link", { hasText: "R-A 产品分析中心" })
      .first();
    const raSidebarVisible = await raSidebar.isVisible();
    const raClass = raSidebarVisible ? await raSidebar.getAttribute("class") : "";
    const runtimeStorageState = await targetPage.evaluate(() => {
      const localStorageKeys = Object.keys(window.localStorage);
      const sessionStorageKeys = Object.keys(window.sessionStorage);
      const staleModuleCacheKeys = [...localStorageKeys, ...sessionStorageKeys].filter(
        (key) =>
          /module|registry|sidebar|capability/i.test(key) &&
          key !== "barong-auth-session",
      );
      return {
        runtimeCacheCleared:
          window.__BARONG_RUNTIME_CACHE_CLEARED__ === true &&
          staleModuleCacheKeys.length === 0,
        staleModuleCacheKeys,
      };
    });
    const backendModuleKeys = new Set(targetTracker.backend_module_keys);

    results.module_registry_source = targetTracker.module_registry_source;
    results.runtime_storage_clean = runtimeStorageState.runtimeCacheCleared;
    results.rw_loaded_from_backend =
      targetTracker.capability_bootstrap_api_hit &&
      backendModuleKeys.has("r.warehouse");
    results.ra_loaded_from_backend =
      targetTracker.capability_bootstrap_api_hit &&
      backendModuleKeys.has("r.analysis");
    results.sidebar_modules_loaded_from_backend =
      results.rw_loaded_from_backend && results.ra_loaded_from_backend;
    results.sidebar_r_w_visible = rwSidebarVisible;
    results.sidebar_r_a_visible = raSidebarVisible;
    results.sidebar_status =
      rwSidebarVisible && raSidebarVisible ? "passed" : "failed";
    results.organization_binding_status = "passed";
    results.r_a_disabled_visible =
      raSidebarVisible && Boolean(raClass?.includes("unavailable"));
    results.mock_data_loaded = true;

    const routeExpectations = new Map([
      ["/r-w/dashboard", "Portable Door Draft Stopper"],
      ["/r-w/products", "Product Warehouse"],
      ["/r-w/rules", "Rule Engine"],
      ["/r-a/dashboard", "locked_until_rw_ready"],
      ["/r-a/analysis", "locked_until_rw_ready"],
    ]);

    for (const [routePath, expectedText] of routeExpectations) {
      await targetPage.goto(`${baseUrl}${routePath}`, {
        waitUntil: "networkidle",
      });
      await textVisible(targetPage, expectedText);
      results.route_status[routePath] = true;
      if (routePath === "/r-w/dashboard") {
        results.route_r_w_accessible = true;
      }
      if (routePath === "/r-a/dashboard") {
        results.route_r_a_accessible = true;
      }
    }

    const otherPage = await browser.newPage();
    await installAuthAndBootstrap(otherPage, { includeTargetOrg: false });
    await otherPage.goto(`${baseUrl}/r-w/dashboard`, {
      waitUntil: "networkidle",
    });
    await textVisible(otherPage, "R 系列模块不可见");
    const hiddenForOtherOrg =
      (await otherPage
        .locator(".navigation-tree-link", { hasText: "R-W 产品数据仓库" })
        .count()) === 0;
    results.organization_binding_status = hiddenForOtherOrg ? "passed" : "failed";
    results.organization_filter_passed = hiddenForOtherOrg;

    return {
      ...results,
      success:
        results.sidebar_r_w_visible &&
        results.sidebar_r_a_visible &&
        results.route_r_w_accessible &&
        results.route_r_a_accessible &&
        results.organization_filter_passed &&
        results.cache_cleared &&
        results.runtime_storage_clean &&
        results.next_build_success &&
        results.sidebar_modules_loaded_from_backend &&
        results.sidebar_status === "passed" &&
        results.organization_binding_status === "passed" &&
        results.r_a_disabled_visible &&
        results.mock_data_loaded &&
        Object.values(results.route_status).every(Boolean),
    };
  } finally {
    await browser.close();
  }
}

function reportFromResult(result) {
  return {
    cache_cleared: Boolean(result.cache_cleared),
    final_status: result.success ? "PASS" : "FAIL",
    organization_filter_passed: Boolean(result.organization_filter_passed),
    route_r_a_accessible: Boolean(result.route_r_a_accessible),
    route_r_w_accessible: Boolean(result.route_r_w_accessible),
    sidebar_r_a_visible: Boolean(result.sidebar_r_a_visible),
    sidebar_r_w_visible: Boolean(result.sidebar_r_w_visible),
  };
}

function fullRebuildReportFromResult(result) {
  const success = Boolean(
    result.next_build_success &&
      result.cache_cleared &&
      result.sidebar_modules_loaded_from_backend &&
      result.sidebar_r_w_visible &&
      result.sidebar_r_a_visible &&
      result.route_r_w_accessible &&
      result.route_r_a_accessible,
  );

  return {
    cache_cleared: Boolean(result.cache_cleared && result.runtime_storage_clean),
    final_status: success ? "PASS" : "FAIL",
    next_build_success: Boolean(result.next_build_success),
    ra_route_accessible: Boolean(result.route_r_a_accessible),
    ra_visible: Boolean(result.sidebar_r_a_visible),
    rw_route_accessible: Boolean(result.route_r_w_accessible),
    rw_visible: Boolean(result.sidebar_r_w_visible),
    sidebar_modules_loaded_from_backend: Boolean(
      result.sidebar_modules_loaded_from_backend,
    ),
  };
}

async function writeJsonReport(targetPath, report) {
  await mkdir(path.dirname(targetPath), { recursive: true });
  await writeFile(targetPath, `${JSON.stringify(report, null, 2)}\n`);
}

async function writeReport(report) {
  await mkdir(path.dirname(reportPath), { recursive: true });
  await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
}

run()
  .then(async (result) => {
    const report = reportFromResult(result);
    const fullRebuildReport = fullRebuildReportFromResult(result);
    await writeReport(report);
    await writeJsonReport(fullRebuildReportPath, fullRebuildReport);
    console.log(JSON.stringify({ ...result, fullRebuildReport, report }, null, 2));
    process.exit(result.success ? 0 : 1);
  })
  .catch(async (error) => {
    await writeReport({
      cache_cleared: process.env.R_FRONTEND_CACHE_CLEARED === "true",
      final_status: "FAIL",
      organization_filter_passed: false,
      route_r_a_accessible: false,
      route_r_w_accessible: false,
      sidebar_r_a_visible: false,
      sidebar_r_w_visible: false,
    }).catch(() => {});
    await writeJsonReport(fullRebuildReportPath, {
      cache_cleared: false,
      final_status: "FAIL",
      next_build_success: process.env.FRONTEND_NEXT_BUILD_SUCCESS === "true",
      ra_route_accessible: false,
      ra_visible: false,
      rw_route_accessible: false,
      rw_visible: false,
      sidebar_modules_loaded_from_backend: false,
    }).catch(() => {});
    console.error(error);
    process.exit(1);
  });
