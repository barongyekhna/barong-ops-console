import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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
  ["DELETE", ["w", "shipping", "classes", uuid]],
  ["POST", ["w", "shipping", "classes", uuid, "sync"]],
  ["GET", ["w", "shipping", "rules"]],
  ["POST", ["w", "shipping", "rules"]],
  ["PATCH", ["w", "shipping", "rules", uuid]],
  ["DELETE", ["w", "shipping", "rules", uuid]],
  ["POST", ["w", "shipping", "simulate"]],
  ["POST", ["w", "shipping", "assign", uuid]],
  ["POST", ["w", "shipping", "assign-all"]],
  ["GET", ["w", "shipping", "board"]],
  ["PATCH", ["w", "shipping", "products", uuid]],
  ["GET", ["w", "orders"]],
  ["PATCH", ["w", "orders", uuid, "tracking"]],
  ["POST", ["w", "orders", uuid, "refresh-tracking"]],
];

const denied = [
  ["PATCH", ["w", "shipping", "classes"]],
  ["GET", ["w", "shipping", "simulate"]],
  ["GET", ["w", "shipping", "assign", uuid]],
  ["POST", ["w", "shipping", "board"]],
  ["POST", ["w", "shipping", "products", uuid]],
  ["PATCH", ["w", "shipping", "rules", "not-a-uuid"]],
  ["POST", ["w", "shipping", "assign", "not-a-uuid"]],
  ["GET", ["w", "shipping", "secrets"]],
  ["GET", ["w", "shipping", "classes", uuid, "sync"]],
  ["POST", ["w", "orders"]],
  ["POST", ["w", "orders", "ingest"]],
  ["POST", ["w", "tracking", "webhook"]],
  ["POST", ["w", "sync", "job-id", "result"]],
  ["POST", ["w", "orders", "not-a-uuid", "refresh-tracking"]],
];

test("W-S 物流网络中枢端点全部经 /api/app 层代理放行", () => {
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

test("W-S 物流网络中枢白名单外的路径与方法一律拒绝", () => {
  for (const [method, path] of denied) {
    assert.equal(
      isAllowedBackendProxyPath(method, path),
      false,
      `${method} /${path.join("/")} should be denied`,
    );
  }
});

test("W-S 三个机器端点只经精确 Nginx location 到达 FastAPI", () => {
  const nginx = readFileSync(
    "deploy/nginx/ops.barongyekhna.com.conf.template",
    "utf8",
  );
  const locations = [
    'location ~ "^/w/sync/[0-9a-f]{32}/result$"',
    "location = /w/orders/ingest",
    "location = /w/tracking/webhook",
  ];

  for (const location of locations) {
    const start = nginx.indexOf(location);
    assert.ok(start >= 0, `${location} must exist`);
    const end = nginx.indexOf("\n    }", start);
    const block = nginx.slice(start, end + 6);
    assert.match(block, /limit_except POST \{ deny all; \}/);
    assert.match(block, /proxy_pass http:\/\/127\.0\.0\.1:8000;/);
  }

  assert.doesNotMatch(nginx, /location\s+(?:\^~\s+)?\/w\/\s*\{/);
});
