import assert from "node:assert/strict";
import test from "node:test";

import {
  getBackendApiPath,
  isAllowedBackendProxyPath,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

const uuid = "01234567-89ab-4def-8123-456789abcdef";

const allowed = [
  ["GET", ["f", "categories", "tree"]],
  ["GET", ["f", "categories", "search"]],
  ["GET", ["f", "categories", "988", "profile"]],
  ["POST", ["f", "categories", "988", "profile"]],
  ["GET", ["f", "runs"]],
  ["POST", ["f", "runs"]],
  ["GET", ["f", "runs", uuid]],
  ["GET", ["f", "keywords"]],
  ["PATCH", ["f", "keywords", uuid]],
  ["GET", ["f", "candidates"]],
  ["POST", ["f", "candidates"]],
  ["PATCH", ["f", "candidates", uuid]],
  ["POST", ["f", "candidates", uuid, "import-to-k"]],
  ["GET", ["f", "quota"]],
];

const denied = [
  // 不存在的动作/方法不放行
  ["DELETE", ["f", "runs", uuid]],
  ["POST", ["f", "categories", "tree"]],
  ["GET", ["f", "candidates", uuid]],
  ["POST", ["f", "keywords"]],
  ["DELETE", ["f", "candidates", uuid]],
  // 非 UUID 段不放行
  ["PATCH", ["f", "keywords", "not-a-uuid"]],
  ["POST", ["f", "candidates", "not-a-uuid", "import-to-k"]],
  // 未知子资源不放行
  ["GET", ["f", "secrets"]],
  ["DELETE", ["f", "categories", "988", "profile"]],
  ["GET", ["f", "categories", "988", "other"]],
];

test("F 系列端点全部经 /api/app 层代理放行", () => {
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

test("F 系列白名单外的路径与方法一律拒绝", () => {
  for (const [method, path] of denied) {
    assert.equal(
      isAllowedBackendProxyPath(method, path),
      false,
      `${method} /${path.join("/")} should be denied`,
    );
  }
});
