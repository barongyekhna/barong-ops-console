import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  DEFAULT_CACHE_TTL_MS,
  MAX_CONCURRENT_FRONTEND_REQUESTS,
  clearFrontendRequestCache,
  getFrontendRequestCacheStats,
  requestWithFrontendCache,
} from "../../frontend/src/lib/request-cache.ts";

function waitForScheduler() {
  return new Promise((resolve) => {
    setImmediate(resolve);
  });
}

test("frontend request cache deduplicates identical in-flight GET requests", async () => {
  clearFrontendRequestCache();

  let calls = 0;
  let releaseRequest;
  const gate = new Promise((resolve) => {
    releaseRequest = resolve;
  });

  const first = requestWithFrontendCache(
    "/modules/me?b=2&a=1",
    { method: "GET" },
    async () => {
      calls += 1;
      await gate;
      return { source: "first" };
    },
  );
  const second = requestWithFrontendCache(
    "/modules/me?a=1&b=2",
    { method: "GET" },
    async () => {
      calls += 1;
      return { source: "second" };
    },
  );

  assert.equal(calls, 1);
  releaseRequest();

  const [firstResult, secondResult] = await Promise.all([first, second]);

  assert.deepEqual(firstResult, { source: "first" });
  assert.deepEqual(secondResult, firstResult);
  assert.equal(calls, 1);
});

test("frontend request cache keeps covered endpoint success values for 60s", async () => {
  clearFrontendRequestCache();

  let calls = 0;
  const first = await requestWithFrontendCache(
    "/module-adapters/registry",
    { method: "GET" },
    async () => ({ call: ++calls }),
  );
  const second = await requestWithFrontendCache(
    "/module-adapters/registry",
    { method: "GET" },
    async () => ({ call: ++calls }),
  );

  assert.equal(DEFAULT_CACHE_TTL_MS, 60_000);
  assert.equal(calls, 1);
  assert.deepEqual(second, first);
});

test("frontend request cache caps concurrent requests at three", async () => {
  clearFrontendRequestCache();

  let active = 0;
  let maxActive = 0;
  const releaseRequests = [];
  const requests = Array.from({ length: 8 }, (_, index) =>
    requestWithFrontendCache(
      `/request-dedup-concurrency-${index}`,
      { method: "GET" },
      async () => {
        active += 1;
        maxActive = Math.max(maxActive, active);
        await new Promise((resolve) => {
          releaseRequests[index] = resolve;
        });
        active -= 1;
        return index;
      },
    ),
  );

  await waitForScheduler();

  assert.equal(MAX_CONCURRENT_FRONTEND_REQUESTS, 3);
  assert.equal(getFrontendRequestCacheStats().active, 3);
  assert.equal(getFrontendRequestCacheStats().queued, 5);
  assert.equal(maxActive, 3);

  for (let index = 0; index < 3; index += 1) {
    releaseRequests[index]();
  }

  while (!releaseRequests[3] || !releaseRequests[4] || !releaseRequests[5]) {
    await waitForScheduler();
  }

  releaseRequests[3]();
  releaseRequests[4]();
  releaseRequests[5]();

  while (!releaseRequests[6] || !releaseRequests[7]) {
    await waitForScheduler();
  }

  releaseRequests[6]();
  releaseRequests[7]();

  assert.deepEqual(await Promise.all(requests), [0, 1, 2, 3, 4, 5, 6, 7]);
  assert.equal(maxActive, 3);
});

test("dashboard consumes capability state without triggering capability refresh", () => {
  const dashboardSource = readFileSync(
    "frontend/src/components/operations-dashboard.tsx",
    "utf8",
  );

  assert.match(dashboardSource, /useFrontendCapabilityState/);
  assert.doesNotMatch(
    dashboardSource,
    /refreshCapabilityState|capabilityState\.refresh\(\)/,
  );
});

test("capability and access providers use bootstrap cache instead of duplicate fetches", () => {
  const capabilityProviderSource = readFileSync(
    "frontend/src/components/capability-state-provider.tsx",
    "utf8",
  );
  const adapterProviderSource = readFileSync(
    "frontend/src/components/adapter-access-provider.tsx",
    "utf8",
  );
  const moduleProviderSource = readFileSync(
    "frontend/src/components/module-access-provider.tsx",
    "utf8",
  );
  const requestCacheSource = readFileSync(
    "frontend/src/lib/request-cache.ts",
    "utf8",
  );

  assert.match(capabilityProviderSource, /getCapabilityBootstrap/);
  assert.match(capabilityProviderSource, /loadingPromiseRef/);
  assert.match(capabilityProviderSource, /loadedAuthKeyRef/);
  assert.match(
    capabilityProviderSource,
    /alreadyLoading or alreadyLoaded, return cachedState/,
  );
  assert.match(
    adapterProviderSource,
    /ADAPTER_ACCESS_MEMORY_CACHE_TTL_MS\s*=\s*60_000/,
  );
  assert.doesNotMatch(
    adapterProviderSource,
    /listModuleAdapterRegistry|listMyModuleAdapters|getExecutionProviderRegistry|getMyExecutionProviders|apiRequest/,
  );
  assert.doesNotMatch(moduleProviderSource, /listMyModules|apiRequest|\/modules\/me/);
  assert.match(requestCacheSource, /normalizedPath === "\/modules\/registry"/);
  assert.match(requestCacheSource, /normalizedPath === "\/modules\/me"/);
  assert.doesNotMatch(requestCacheSource, /normalizedPath === "\/jobs"/);
  assert.match(requestCacheSource, /normalizedPath\.startsWith\("\/module-adapters\/"\)/);
  assert.match(requestCacheSource, /normalizedPath\.startsWith\("\/execution-providers\/"\)/);
  assert.match(requestCacheSource, /normalizedPath\.startsWith\("\/live-gate\/"\)/);
});

test("jobs-specific frontend API handling is removed", () => {
  const apiSource = readFileSync("frontend/src/lib/api.ts", "utf8");
  const consoleSource = readFileSync(
    "frontend/src/components/product-resource-console.tsx",
    "utf8",
  );

  assert.doesNotMatch(apiSource, /JOBS_API_TIMEOUT_MS/);
  assert.doesNotMatch(apiSource, /pathname === "\/jobs"/);
  assert.doesNotMatch(apiSource, /pathname\.startsWith\("\/jobs\/"\)/);
  assert.match(consoleSource, /EMPTY_LIST_PAYLOAD/);
  assert.match(consoleSource, /fallbackToEmptyOnListError/);
  assert.match(consoleSource, /AbortController/);
  assert.match(consoleSource, /isApiAbortError/);
});

test("product creation uses idempotency and dropdown-only market selection", () => {
  const productFormSource = readFileSync(
    "frontend/src/modules/k/product-knowledge/ProductForm.tsx",
    "utf8",
  );
  const productApiSource = readFileSync(
    "frontend/src/modules/k/product-knowledge/api.ts",
    "utf8",
  );
  const productListSource = readFileSync(
    "frontend/src/modules/k/product-knowledge/ProductList.tsx",
    "utf8",
  );
  const proxySource = readFileSync(
    "frontend/src/app/api/backend/[...path]/route.ts",
    "utf8",
  );

  assert.doesNotMatch(productFormSource, /marketSearch/);
  assert.doesNotMatch(productFormSource, /市场搜索|Market Search/);
  assert.match(productFormSource, /submitLockRef/);
  assert.match(productFormSource, /<select[\s\S]*value=\{values\.target_market\}/);
  assert.equal((productFormSource.match(/type="submit"/g) ?? []).length, 1);
  assert.match(productFormSource, /styles\.formFooter/);
  assert.ok(
    productFormSource.indexOf('type="submit"') >
      productFormSource.indexOf("styles.formFooter"),
  );
  assert.match(productApiSource, /Idempotency-Key/);
  assert.match(proxySource, /idempotency-key/);
  assert.match(
    productApiSource,
    /产品创建失败，请稍后重试或检查SKU\/变体信息/,
  );
  assert.match(productListSource, /PRODUCT_CREATE_FAILURE_MESSAGE/);
});

test("product management uses full-list route, safe delete, and clean K labels", () => {
  const productPageSource = readFileSync(
    "frontend/src/app/(console)/products/page.tsx",
    "utf8",
  );
  const fullProductPageSource = readFileSync(
    "frontend/src/app/(console)/products/full/page.tsx",
    "utf8",
  );
  const productListSource = readFileSync(
    "frontend/src/modules/k/product-knowledge/ProductList.tsx",
    "utf8",
  );
  const productFormSource = readFileSync(
    "frontend/src/modules/k/product-knowledge/ProductForm.tsx",
    "utf8",
  );
  const productDetailSource = readFileSync(
    "frontend/src/modules/k/product-knowledge/ProductDetail.tsx",
    "utf8",
  );
  const proxySource = readFileSync(
    "frontend/src/app/api/backend/[...path]/route.ts",
    "utf8",
  );
  const researchPanelSource = readFileSync(
    "frontend/src/modules/k15/research-trigger/ResearchTriggerPanel.tsx",
    "utf8",
  );
  const serpPanelSource = readFileSync(
    "frontend/src/modules/k16/serp-trigger/SERPTriggerPanel.tsx",
    "utf8",
  );
  const keywordTypesSource = readFileSync(
    "frontend/src/modules/k19/keywords/types.ts",
    "utf8",
  );
  const riskTypesSource = readFileSync(
    "frontend/src/modules/k20/risk/types.ts",
    "utf8",
  );

  assert.match(productPageSource, /<ProductListFull \/>/);
  assert.doesNotMatch(
    productPageSource,
    /ResearchTriggerPanel|SERPTriggerPanel|KeywordPanel|RiskPanel|<ProductList \/>/,
  );
  assert.match(fullProductPageSource, /ProductListFull/);
  assert.match(productListSource, /window\.open\(\s*"\/products\/full"/);
  assert.match(productListSource, /打开产品列表/);
  assert.match(productListSource, /PRODUCT_LIST_PAGE_SIZE\s*=\s*25/);
  assert.match(productListSource, /openProductId/);
  assert.doesNotMatch(productListSource, /selectedProductId/);
  assert.match(productListSource, /deleteProduct/);
  assert.match(productListSource, /确认删除/);
  assert.match(productListSource, /deleteConfirmation\.trim\(\) === deleteConfirmationKey/);
  assert.match(productListSource, /displayProductKey/);
  assert.match(productDetailSource, /onCollapse/);
  assert.match(productDetailSource, /启动关键词调研/);
  assert.match(productDetailSource, /KEYWORD_STEPS/);
  assert.match(productDetailSource, /keywordProgress/);
  assert.match(productDetailSource, /非风险关键词/);
  assert.match(productDetailSource, /人工添加非风险关键词/);
  assert.match(productDetailSource, /onApproveSellingPoints/);
  assert.match(productDetailSource, /onDeleteMedia/);
  assert.match(productDetailSource, /提交图片/);
  assert.match(productDetailSource, /提交卖点/);
  assert.match(productDetailSource, /P系列/);
  assert.doesNotMatch(productDetailSource, /onExportWorkflow|exportResult|导出/);
  assert.match(productDetailSource, /formatVariantDisplayName/);
  assert.match(productFormSource, /variantAttributeBuilder/);
  assert.match(productFormSource, /addVariantAttribute/);
  assert.match(productFormSource, /attribute_schema: "attribute_builder_v1"/);
  assert.doesNotMatch(productFormSource, /attributesJson|attributes_text|Variant SKU Preview/);
  assert.match(proxySource, /method === "GET" \|\| method === "PATCH" \|\| method === "DELETE"/);

  assert.doesNotMatch(productDetailSource, />K14|K14 Selling Points|auxiliary K14/);
  assert.doesNotMatch(researchPanelSource, />K15</);
  assert.doesNotMatch(serpPanelSource, />K16</);
  assert.doesNotMatch(keywordTypesSource, /K15 research|K16 SERP|K17 ChatGPT|K18 Claude/);
  assert.doesNotMatch(riskTypesSource, /K17 pre-filter|K18 validated/);
});

test("dashboard initial load renders partial state without all-settled blocking", () => {
  const dashboardSource = readFileSync(
    "frontend/src/components/operations-dashboard.tsx",
    "utf8",
  );

  assert.match(dashboardSource, /EMPTY_DASHBOARD_STATE/);
  assert.match(dashboardSource, /loadResource/);
  assert.match(dashboardSource, /AbortController/);
  assert.doesNotMatch(dashboardSource, /Promise\.allSettled/);
  assert.doesNotMatch(dashboardSource, /DashboardState \| null/);
  assert.doesNotMatch(dashboardSource, /state === null/);
});

test("approval list requests are bounded and render degraded state", () => {
  const approvalApiSource = readFileSync("frontend/src/lib/approval.ts", "utf8");
  const approvalViewSource = readFileSync(
    "frontend/src/components/approval-product-view.tsx",
    "utf8",
  );

  assert.match(approvalApiSource, /APPROVAL_LIST_DEFAULT_LIMIT\s*=\s*10/);
  assert.match(approvalApiSource, /APPROVAL_LIST_MAX_LIMIT\s*=\s*100/);
  assert.match(approvalApiSource, /APPROVAL_LIST_TIMEOUT_MS\s*=\s*12_000/);
  assert.match(approvalApiSource, /retryLimit:\s*0/);
  assert.match(approvalApiSource, /record\.status === "degraded"/);
  assert.match(approvalViewSource, /ApiTimeoutError/);
  assert.match(approvalViewSource, /approvalListErrorText/);
  assert.match(approvalViewSource, /data\.status === "degraded"/);
  assert.doesNotMatch(approvalViewSource, /setInterval/);
});
