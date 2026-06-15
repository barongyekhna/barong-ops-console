import test from "node:test";
import assert from "node:assert/strict";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";

test("backend proxy precisely allows C15C payload standardization paths", () => {
  const allowedGetPaths = [
    ["payload-standardization", "model"],
    ["payload-standardization", "normalization-engine"],
    ["payload-standardization", "context-rules"],
    ["payload-standardization", "workflow-mapping"],
    ["payload-standardization", "completion-status"],
  ];

  for (const path of allowedGetPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), true);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
    assert.equal(isAllowedBackendProxyPath("PATCH", path), false);
    assert.equal(isAllowedBackendProxyPath("DELETE", path), false);
  }

  assert.equal(
    isAllowedBackendProxyPath("POST", [
      "payload-standardization",
      "normalize",
    ]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", [
      "payload-standardization",
      "normalize",
    ]),
    false,
  );
});

test("backend proxy denies C15C wildcard and runtime action paths", () => {
  const deniedPaths = [
    ["payload-standardization"],
    ["payload-standardization", "model", "extra"],
    ["payload-standardization", "run"],
    ["payload-standardization", "execute"],
    ["payload-standardization", "invoke"],
    ["payload-standardization", "sync"],
    ["payload-standardization", "n8n"],
    ["payload-standardization", "normalize", "extra"],
    ["payload-standardization", "dispatch"],
  ];

  for (const path of deniedPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), false);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
  }
});
