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
    getBackendApiPath("GET", ["jobs"]),
    "/api/app/jobs",
  );
  assert.equal(
    getBackendApiPath("GET", ["permissions", "me"]),
    "/api/app/permissions/me",
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
    [["n8n-test", "run"], "/api/control-plane/n8n-test/run"],
  ];

  for (const [path, expectedBackendPath] of controlPlanePaths) {
    const method = path.at(-1) === "run" ? "POST" : "GET";

    assert.equal(isAllowedBackendProxyPath(method, path), true);
    assert.equal(getBackendApiPath(method, path), expectedBackendPath);
  }
});

test("backend proxy denies direct control-plane namespace and unsafe callbacks", () => {
  assert.equal(
    getBackendApiPath("GET", ["api", "control-plane", "modules"]),
    null,
  );
  assert.equal(getBackendApiPath("POST", ["webhook-gateway", "ingress"]), null);
  assert.equal(getBackendApiPath("POST", ["callback-handler", "receiver"]), null);
  assert.equal(getBackendApiPath("POST", ["execution", "submit"]), null);
});
