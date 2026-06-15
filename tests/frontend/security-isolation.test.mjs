import assert from "node:assert/strict";
import test from "node:test";

import {
  isAllowedBackendProxyPath,
  isBlockedSecurityIsolationPath,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

test("backend proxy blocks C15G direct webhook and n8n bypass paths", () => {
  const blockedPaths = [
    ["webhook"],
    ["webhook", "direct"],
    ["n8n"],
    ["n8n", "webhook"],
    ["webhook-gateway", "ingress"],
    ["https%3A", "n8n.invalid", "webhook", "redacted"],
  ];

  for (const path of blockedPaths) {
    assert.equal(isBlockedSecurityIsolationPath(path), true);
    assert.equal(isAllowedBackendProxyPath("GET", path), false);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
  }
});

test("backend proxy keeps existing C15 read paths exact and non-bypass", () => {
  assert.equal(
    isBlockedSecurityIsolationPath([
      "module-workflow-bindings",
      "completion-status",
    ]),
    false,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", [
      "module-workflow-bindings",
      "completion-status",
    ]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("POST", [
      "module-workflow-bindings",
      "completion-status",
    ]),
    false,
  );
});
