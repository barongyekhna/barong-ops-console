import assert from "node:assert/strict";
import test from "node:test";

import {
  getBackendApiPath,
  isAllowedBackendProxyPath,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

const uuid = "01234567-89ab-4def-8123-456789abcdef";

const allowed = [
  ["GET", ["w", "shipping", "classes"]],
  ["POST", ["w", "shipping", "classes"]],
  ["PATCH", ["w", "shipping", "classes", uuid]],
  ["GET", ["w", "shipping", "rules"]],
  ["POST", ["w", "shipping", "rules"]],
  ["PATCH", ["w", "shipping", "rules", uuid]],
  ["DELETE", ["w", "shipping", "rules", uuid]],
  ["POST", ["w", "shipping", "simulate"]],
  ["POST", ["w", "shipping", "assign", uuid]],
  ["POST", ["w", "shipping", "assign-all"]],
  ["GET", ["w", "shipping", "board"]],
  ["PATCH", ["w", "shipping", "products", uuid]],
];

const denied = [
  ["DELETE", ["w", "shipping", "classes", uuid]],
  ["PATCH", ["w", "shipping", "classes"]],
  ["GET", ["w", "shipping", "simulate"]],
  ["GET", ["w", "shipping", "assign", uuid]],
  ["POST", ["w", "shipping", "board"]],
  ["POST", ["w", "shipping", "products", uuid]],
  ["PATCH", ["w", "shipping", "rules", "not-a-uuid"]],
  ["POST", ["w", "shipping", "assign", "not-a-uuid"]],
  ["GET", ["w", "shipping", "secrets"]],
];

test("W-A 运费中枢端点全部经 /api/app 层代理放行", () => {
  for (const [method, path] of allowed) {
    assert.equal(
      isAllowedBackendProxyPath(method, path),
      true,
      `${method} /${path.join("/")} should be allowed`,
    );
    assert.equal(
      getBackendApiPath(method, path),
      `/api/app/${path.join("/")}`,
      `${method} /${path.join("/")} should map to the app layer`,
    );
  }
});

test("W-A 运费中枢白名单外的路径与方法一律拒绝", () => {
  for (const [method, path] of denied) {
    assert.equal(
      isAllowedBackendProxyPath(method, path),
      false,
      `${method} /${path.join("/")} should be denied`,
    );
  }
});
