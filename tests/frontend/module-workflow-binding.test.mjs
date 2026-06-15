import assert from "node:assert/strict";
import test from "node:test";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";

test("backend proxy precisely allows C15F module workflow binding read paths", () => {
  const allowedPaths = [
    ["module-workflow-bindings", "model"],
    ["module-workflow-bindings", "enforcement"],
    ["module-workflow-bindings", "access-control"],
    ["module-workflow-bindings", "isolation-rules"],
    ["module-workflow-bindings", "decision"],
    ["module-workflow-bindings", "validation"],
    ["module-workflow-bindings", "completion-status"],
  ];

  for (const path of allowedPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), true);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
    assert.equal(isAllowedBackendProxyPath("PATCH", path), false);
    assert.equal(isAllowedBackendProxyPath("DELETE", path), false);
  }
});

test("backend proxy denies C15F wildcard and runtime action paths", () => {
  const deniedPaths = [
    ["module-workflow-bindings"],
    ["module-workflow-bindings", "model", "extra"],
    ["module-workflow-bindings", "run"],
    ["module-workflow-bindings", "execute"],
    ["module-workflow-bindings", "invoke"],
    ["module-workflow-bindings", "sync"],
    ["module-workflow-bindings", "dispatch"],
    ["module-workflow-bindings", "n8n"],
    ["module-workflow-bindings", "workflows", "auto-route"],
  ];

  for (const path of deniedPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), false);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
  }
});
