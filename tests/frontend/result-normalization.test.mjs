import assert from "node:assert/strict";
import test from "node:test";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";

test("backend proxy precisely allows C15E result normalization paths", () => {
  const allowedGetPaths = [
    ["result-normalization", "normalization-engine"],
    ["result-normalization", "schema-mapping"],
    ["result-normalization", "module-adapters"],
    ["result-normalization", "ui-output-structure"],
    ["result-normalization", "completion-status"],
  ];

  for (const path of allowedGetPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), true);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
    assert.equal(isAllowedBackendProxyPath("PATCH", path), false);
    assert.equal(isAllowedBackendProxyPath("DELETE", path), false);
  }

  assert.equal(
    isAllowedBackendProxyPath("POST", ["result-normalization", "normalize"]),
    true,
  );
  assert.equal(
    isAllowedBackendProxyPath("GET", ["result-normalization", "normalize"]),
    false,
  );
});

test("backend proxy denies C15E wildcard and runtime action paths", () => {
  const deniedPaths = [
    ["result-normalization"],
    ["result-normalization", "normalization-engine", "extra"],
    ["result-normalization", "run"],
    ["result-normalization", "execute"],
    ["result-normalization", "invoke"],
    ["result-normalization", "sync"],
    ["result-normalization", "n8n"],
    ["result-normalization", "normalize", "extra"],
    ["result-normalization", "dispatch"],
  ];

  for (const path of deniedPaths) {
    assert.equal(isAllowedBackendProxyPath("GET", path), false);
    assert.equal(isAllowedBackendProxyPath("POST", path), false);
  }
});
