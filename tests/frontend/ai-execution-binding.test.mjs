import test from "node:test";
import assert from "node:assert/strict";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";

test("backend proxy precisely allows C14X-A AI execution binding read paths", () => {
  const allowedPaths = [
    ["ai-execution-bindings", "registry"],
    ["ai-execution-bindings", "rules"],
    ["ai-execution-bindings", "execution-flow"],
    ["ai-execution-bindings", "validation"],
    ["ai-execution-bindings", "ui-interaction"],
    ["ai-execution-bindings", "completion-status"],
  ];

  for (const path of allowedPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), true);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
    assert.equal(isAllowedBackendProxyPath("PATCH", path), false);
    assert.equal(isAllowedBackendProxyPath("DELETE", path), false);
  }
});

test("backend proxy denies C14X-A AI execution binding wildcard and action paths", () => {
  const deniedPaths = [
    ["ai-execution-bindings"],
    ["ai-execution-bindings", "registry", "extra"],
    ["ai-execution-bindings", "run"],
    ["ai-execution-bindings", "execute"],
    ["ai-execution-bindings", "invoke"],
    ["ai-execution-bindings", "sync"],
    ["ai-execution-bindings", "models", "auto-select"],
  ];

  for (const path of deniedPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), false);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
  }
});

test("backend proxy precisely allows C14X-B model lock read paths", () => {
  const allowedPaths = [
    ["model-locks", "registry"],
    ["model-locks", "rules"],
    ["model-locks", "enforcement"],
    ["model-locks", "validation"],
    ["model-locks", "request-validation"],
    ["model-locks", "integration"],
    ["model-locks", "completion-status"],
  ];

  for (const path of allowedPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), true);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
    assert.equal(isAllowedBackendProxyPath("PATCH", path), false);
    assert.equal(isAllowedBackendProxyPath("DELETE", path), false);
  }
});

test("backend proxy denies C14X-B model lock wildcard and action paths", () => {
  const deniedPaths = [
    ["model-locks"],
    ["model-locks", "registry", "extra"],
    ["model-locks", "run"],
    ["model-locks", "execute"],
    ["model-locks", "invoke"],
    ["model-locks", "sync"],
    ["model-locks", "models", "fallback"],
    ["model-locks", "models", "auto-select"],
  ];

  for (const path of deniedPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), false);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
  }
});

test("backend proxy precisely allows C14X-C capability binding read paths", () => {
  const allowedPaths = [
    ["capability-bindings", "routing-model"],
    ["capability-bindings", "model-mapping"],
    ["capability-bindings", "module-bindings"],
    ["capability-bindings", "enforcement"],
    ["capability-bindings", "validation"],
    ["capability-bindings", "request-validation"],
    ["capability-bindings", "integration"],
    ["capability-bindings", "completion-status"],
  ];

  for (const path of allowedPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), true);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
    assert.equal(isAllowedBackendProxyPath("PATCH", path), false);
    assert.equal(isAllowedBackendProxyPath("DELETE", path), false);
  }
});

test("backend proxy denies C14X-C capability binding wildcard and action paths", () => {
  const deniedPaths = [
    ["capability-bindings"],
    ["capability-bindings", "routing-model", "extra"],
    ["capability-bindings", "run"],
    ["capability-bindings", "execute"],
    ["capability-bindings", "invoke"],
    ["capability-bindings", "sync"],
    ["capability-bindings", "models", "fallback"],
    ["capability-bindings", "capabilities", "auto-route"],
  ];

  for (const path of deniedPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), false);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
  }
});

test("backend proxy precisely allows C14X-D module allocation read paths", () => {
  const allowedPaths = [
    ["module-allocations", "registry"],
    ["module-allocations", "assignment-model"],
    ["module-allocations", "categories"],
    ["module-allocations", "budget-system"],
    ["module-allocations", "enforcement"],
    ["module-allocations", "integration-flow"],
    ["module-allocations", "validation"],
    ["module-allocations", "request-validation"],
    ["module-allocations", "completion-status"],
  ];

  for (const path of allowedPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), true);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
    assert.equal(isAllowedBackendProxyPath("PATCH", path), false);
    assert.equal(isAllowedBackendProxyPath("DELETE", path), false);
  }
});

test("backend proxy denies C14X-D module allocation wildcard and action paths", () => {
  const deniedPaths = [
    ["module-allocations"],
    ["module-allocations", "registry", "extra"],
    ["module-allocations", "run"],
    ["module-allocations", "execute"],
    ["module-allocations", "invoke"],
    ["module-allocations", "sync"],
    ["module-allocations", "capabilities", "auto-route"],
    ["module-allocations", "budgets", "unlimited"],
  ];

  for (const path of deniedPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), false);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
  }
});
