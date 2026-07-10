import assert from "node:assert/strict";
import test from "node:test";

import {
  getBackendApiPath,
  isAllowedBackendProxyPath,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

test("backend proxy maps public and app paths to non-control-plane APIs", () => {
  assert.equal(
    getBackendApiPath("GET", ["health"]),
    "/api/public/health",
  );
  assert.equal(
    getBackendApiPath("POST", ["auth", "login"]),
    "/api/public/auth/login",
  );
  assert.equal(
    getBackendApiPath("GET", ["approval", "list"]),
    "/api/app/approval/list",
  );
  assert.equal(
    getBackendApiPath("GET", ["reviews"]),
    "/api/app/reviews",
  );
  assert.equal(
    getBackendApiPath("GET", ["reviews", "organizations"]),
    "/api/app/reviews/organizations",
  );
  assert.equal(
    getBackendApiPath("GET", ["reviews", "module-registry"]),
    "/api/app/reviews/module-registry",
  );
  assert.equal(
    getBackendApiPath("GET", [
      "reviews",
      "organizations",
      "org_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
      "users",
      "42",
      "actions",
    ]),
    "/api/app/reviews/organizations/org_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee/users/42/actions",
  );
  assert.equal(
    getBackendApiPath("GET", ["operation-logs"]),
    "/api/app/operation-logs",
  );
  assert.equal(
    getBackendApiPath("GET", ["permissions", "me"]),
    "/api/app/permissions/me",
  );
  assert.equal(
    getBackendApiPath("GET", ["r", "analysis", "status"]),
    "/api/app/r/analysis/status",
  );
  assert.equal(
    getBackendApiPath("GET", ["r", "analysis", "profit", "snapshots"]),
    "/api/app/r/analysis/profit/snapshots",
  );
  assert.equal(
    getBackendApiPath("POST", ["r", "analysis", "supplier-search"]),
    "/api/app/r/analysis/supplier-search",
  );
});

test("backend proxy maps C14 C15 and execution paths to control-plane only", () => {
  const controlPlanePaths = [
    [["modules", "registry"], "/api/control-plane/modules/registry"],
    [
      ["ai-execution-bindings", "registry"],
      "/api/control-plane/ai-execution-bindings/registry",
    ],
    [
      ["capability-bindings", "routing-model"],
      "/api/control-plane/capability-bindings/routing-model",
    ],
    [
      ["module-workflow-bindings", "completion-status"],
      "/api/control-plane/module-workflow-bindings/completion-status",
    ],
    [
      ["execution-providers", "registry"],
      "/api/control-plane/execution-providers/registry",
    ],
    [["live-gate", "readiness"], "/api/control-plane/live-gate/readiness"],
    [
      ["live-gate", "production-readiness"],
      "/api/control-plane/live-gate/production-readiness",
    ],
    [["live-gate", "policies"], "/api/control-plane/live-gate/policies"],
    [["key-health", "summary"], "/api/control-plane/key-health/summary"],
    [["key-health", "runs"], "/api/control-plane/key-health/runs"],
  ];

  for (const [path, expectedBackendPath] of controlPlanePaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), true);
    assert.equal(getBackendApiPath("GET", path), expectedBackendPath);
  }
});

test("backend proxy exposes only the key health read and trigger endpoints", () => {
  assert.equal(
    getBackendApiPath("POST", ["key-health", "run"]),
    "/api/control-plane/key-health/run",
  );
  assert.equal(getBackendApiPath("DELETE", ["key-health", "run"]), null);
  assert.equal(getBackendApiPath("GET", ["key-health", "unknown"]), null);
});

test("backend proxy denies direct control-plane namespace and unsafe callbacks", () => {
  assert.equal(
    getBackendApiPath("GET", ["api", "control-plane", "modules"]),
    null,
  );
  assert.equal(getBackendApiPath("POST", ["webhook-gateway", "ingress"]), null);
  assert.equal(getBackendApiPath("POST", ["callback-handler", "receiver"]), null);
  assert.equal(getBackendApiPath("POST", ["execution", "submit"]), null);
  assert.equal(getBackendApiPath("POST", ["n8n-test", "run"]), null);
  assert.equal(getBackendApiPath("GET", ["reviews", "demo.review"]), null);
  assert.equal(getBackendApiPath("POST", ["reviews"]), null);
  assert.equal(
    getBackendApiPath("POST", ["reviews", "demo.review", "decision"]),
    null,
  );
});
