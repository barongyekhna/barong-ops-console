import assert from "node:assert/strict";
import test from "node:test";

import {
  getBackendApiPath,
  isAllowedBackendProxyPath,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

const uuid = "01234567-89ab-4def-8123-456789abcdef";

const allowed = [
  ["GET", ["k", "categories", "123", "spec-template"]],
  ["PUT", ["k", "categories", "123", "spec-template"]],
  ["POST", ["k", "categories", "123", "spec-template", "draft"]],
  ["POST", ["k", "products", uuid, "specs", "parse-paste"]],
];

const denied = [
  ["POST", ["k", "categories", "123", "spec-template"]],
  ["PATCH", ["k", "categories", "123", "spec-template"]],
  ["GET", ["k", "categories", "123", "spec-template", "draft"]],
  ["GET", ["k", "products", uuid, "specs", "parse-paste"]],
  ["POST", ["k", "products", "not-a-uuid", "specs", "parse-paste"]],
  ["GET", ["k", "categories", "not-a-category", "spec-template"]],
  ["GET", ["k", "categories", "123", "spec-template", "other"]],
  ["POST", ["k", "products", uuid, "specs", "parse-paste", "other"]],
];

test("Round 9 K endpoints map through the exact application proxy allowlist", () => {
  for (const [method, path] of allowed) {
    assert.equal(
      isAllowedBackendProxyPath(method, path),
      true,
      `${method} /${path.join("/")} should be allowed`,
    );
    assert.equal(
      getBackendApiPath(method, path),
      `/api/app/${path.join("/")}`,
    );
  }
});

test("Round 9 proxy rejects neighboring methods and malformed resource ids", () => {
  for (const [method, path] of denied) {
    assert.equal(
      isAllowedBackendProxyPath(method, path),
      false,
      `${method} /${path.join("/")} should be denied`,
    );
  }
});
