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
