import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";

// ---------------------------------------------------------------------------
// Anti-drift ratchet between the backend route table and the frontend proxy
// allowlist. Historically, "服务暂时不可用" incidents were caused by adding a
// backend endpoint and forgetting to register it in the proxy. This test
// enumerates every /api/public, /api/app and /api/control-plane route straight
// from the FastAPI app and requires each one to be either:
//   1. reachable through the frontend proxy allowlist, or
//   2. listed in KNOWN_UNPROXIED below with a reason.
// Adding a new backend endpoint without touching either list fails this test.
// ---------------------------------------------------------------------------

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
);

// Endpoints that are deliberately NOT exposed through the browser proxy.
// Format: "METHOD /api/..." (path parameters in FastAPI {param} syntax).
// Every entry needs a reason comment — this list is an audited contract, not
// a dumping ground.
const KNOWN_UNPROXIED = new Set([
  // -- server-to-server callbacks and ingest (must never be browser-reachable)
  "POST /api/app/notifications/ingest",
  // CS inbound is authenticated server-to-server form ingest and must bypass Next.
  "POST /api/public/cs/inbound",
  // Public order tracking is called server-to-server by the WordPress plugin
  // and is reserved for direct Nginx routing instead of the Next proxy.
  "POST /api/public/track/lookup",
  // H health ingest is a machine endpoint routed directly by Nginx,
  // never through Next.
  "POST /api/app/h/ingest",
  "POST /api/app/p/uploads/{job_id}/result",
  // GEO 发布与产品页反链：n8n 拉发布包 / 反链包 + 回报，一单一钥 token 鉴权。
  // 同 P 上架流，走裸挂载的机器路由，浏览器永远不该碰到 —— 刻意不进代理白名单。
  "GET /api/app/geo/clusters/{cluster_id}/publish-package",
  "POST /api/app/geo/publishes/{job_id}/result",
  "GET /api/app/geo/backlinks/{job_id}/package",
  "POST /api/app/geo/backlinks/{job_id}/result",
  // SEO 发布：n8n 拉发布包 + 回报，一单一钥 token 鉴权，走裸挂载的机器路由。
  // 与 GEO 同规——浏览器永远不该碰到，所以刻意不进代理白名单。
  "GET /api/app/seo/publishes/{job_id}/package",
  "POST /api/app/seo/publishes/{job_id}/result",
  // B2B 产品页小窗：n8n 拉包 + 回报，一单一钥 token 鉴权。
  // 走裸挂载的路由，浏览器永远不该碰到——所以刻意不进代理白名单。
  "GET /api/app/b2b/widget-jobs/{job_id}/package",
  "POST /api/app/b2b/widget-jobs/{job_id}/result",
  // 内链网每日兜底：n8n 定时打（03:20），共享密钥鉴权 fail-closed。
  // 人要立刻刷走 /seo/link-net/refresh（带会话）——这条只给机器。
  "POST /api/app/content/link-map/refresh",
  // B2B 批发页每日重发：n8n 定时打，共享密钥鉴权（H 哨兵同款）。
  // 人要重发走 /b2b/website/publish（带会话）——这条只给机器，不进白名单。
  "POST /api/app/b2b/website/republish",
  "GET /api/app/p/jobs/{job_id}/media/{asset_id}/file",
  // W-S sync callbacks, Woo order ingest and 17TRACK updates are server-to-server only.
  "POST /api/app/w/sync/{job_id}/result",
  "POST /api/app/w/orders/ingest",
  // Jetpack traffic ingest is pushed by n8n (barongWtraffic001) over the docker network only.
  "POST /api/app/w/traffic/ingest",
  "POST /api/app/w/tracking/webhook",
  // C19 byte-plane session authorization is called only by Nginx auth_request.
  "GET /api/app/c19/assets/transfers/authorize",
  "POST /api/control-plane/n8n-test/callback",
  "POST /api/control-plane/webhook-gateway/ingress",
  "POST /api/control-plane/callback-handler/receiver",
  "POST /api/control-plane/callback-handler/context-bindings",

  // -- security-firewall decoy routes: they exist to hard-404 probes and the
  //    proxy blocks the webhook/n8n prefixes outright
  ...["GET", "POST", "PUT", "PATCH", "DELETE"].flatMap((method) => [
    `${method} /api/public/webhook`,
    `${method} /api/public/webhook/{path:path}`,
    `${method} /api/public/n8n`,
    `${method} /api/public/n8n/{path:path}`,
  ]),

  // -- internal health alias used by container checks
  "GET /api/backend/health",

  // -- C18 module-binding service APIs superseded by the module control
  //    center UI; kept server-side only
  "POST /api/app/module/bind",
  "GET /api/app/module/{module_id}/bindings",
  "GET /api/app/org/{org_id}/modules",
  "GET /api/app/org/{org_id}/visible-modules",
  "GET /api/app/org/{org_id}/shared-modules",
  "POST /api/app/module/shared/create",
  "POST /api/app/module/shared/update-orgs",
  "GET /api/app/module/shared/list",

  // -- detail endpoint not surfaced in the operation-logs UI (list only)
  "GET /api/app/operation-logs/{operation_id}",

  // -- pre-overhaul R-A API surface; the current UI drives
  //    /r/analysis/framework|status|profit/*|runs/{id}/status instead
  "GET /api/app/r/analysis/overview",
  "GET /api/app/r/analysis/profit",
  "POST /api/app/r/analysis/runs",
  "GET /api/app/r/analysis/runs/latest",
  "GET /api/app/r/analysis/runs/{run_id}",
  "POST /api/app/r/analysis/runs/{run_id}/cancel",
  "GET /api/app/r/analysis/candidates",
  "POST /api/app/r/analysis/candidates/import-from-rw",
  "GET /api/app/r/analysis/suppliers",
  "GET /api/app/rw/ingestion/status",

  // -- dormant C-series control-plane contract/design endpoints; no UI reads
  //    them today (candidates for productization or removal later)
  "POST /api/control-plane/foundation-demo/run",
  "GET /api/control-plane/foundation-demo/latest",
  "POST /api/control-plane/n8n-test/run",
  "GET /api/control-plane/n8n-test/latest",
  "POST /api/control-plane/module-adapters/{adapter_key}/actions/{action_key}/request",
  "GET /api/control-plane/api-key-orchestration/key-types",
  "POST /api/control-plane/api-key-orchestration/keys/{key_id}/validate",
  "GET /api/control-plane/workflow-registry/registry",
  "GET /api/control-plane/workflow-registry/workflows/{workflow_id}",
  "GET /api/control-plane/workflow-registry/module-bindings",
  "GET /api/control-plane/workflow-registry/modules/{module}/workflows",
  "GET /api/control-plane/workflow-registry/status-management",
  "GET /api/control-plane/workflow-registry/rules",
  "GET /api/control-plane/workflow-registry/decision",
  "GET /api/control-plane/workflow-registry/validation",
  "GET /api/control-plane/workflow-registry/system-flow",
  "GET /api/control-plane/workflow-registry/completion-status",
  "GET /api/control-plane/webhook-gateway/design",
  "GET /api/control-plane/webhook-gateway/signature-model",
  "GET /api/control-plane/webhook-gateway/payload-format",
  "GET /api/control-plane/webhook-gateway/workflow-lookup-flow",
  "GET /api/control-plane/webhook-gateway/completion-status",
  "GET /api/control-plane/callback-handler/results/{context_id}",
  "GET /api/control-plane/callback-handler/design",
  "GET /api/control-plane/callback-handler/context-binding",
  "GET /api/control-plane/callback-handler/status-management",
  "GET /api/control-plane/callback-handler/result-storage",
  "GET /api/control-plane/callback-handler/module-notifications",
  "GET /api/control-plane/callback-handler/completion-status",
  "POST /api/control-plane/failure-handling/failures",
  "POST /api/control-plane/failure-handling/timeouts/evaluate",
  "GET /api/control-plane/failure-handling/dlq",
  "GET /api/control-plane/failure-handling/dlq/{context_id}",
  "POST /api/control-plane/failure-handling/recovery/replay",
  "GET /api/control-plane/failure-handling/retry-system-design",
  "GET /api/control-plane/failure-handling/timeout-handling",
  "GET /api/control-plane/failure-handling/dead-letter-queue",
  "GET /api/control-plane/failure-handling/fallback-strategy",
  "GET /api/control-plane/failure-handling/recovery-flow",
  "GET /api/control-plane/failure-handling/completion-status",
  "POST /api/control-plane/live-gate/canary",
  "POST /api/control-plane/live-gate/policies",
  "POST /api/control-plane/live-gate/rollback/consistency",
  "POST /api/control-plane/live-gate/rollback/failure",
  "POST /api/control-plane/live-gate/rollback/restore",
]);

// The drift check needs the backend source tree plus a Python runtime; the
// frontend Docker build gate copies only frontend/ + tests/frontend/, so the
// ratchet runs on the host / CI checkout and skips inside the image build.
const venvPython = path.join(repoRoot, ".venv", "bin", "python");
const backendAvailable =
  existsSync(path.join(repoRoot, "backend", "app", "main.py")) &&
  existsSync(venvPython);
const skipReason = backendAvailable
  ? false
  : "backend source tree + .venv python not available in this environment";

function loadBackendRoutes() {
  const python = venvPython;
  const script = [
    "import json",
    "from backend.app.main import app",
    "routes = []",
    "for r in app.routes:",
    "    methods = sorted(m for m in (getattr(r, 'methods', None) or []) if m not in {'HEAD', 'OPTIONS'})",
    "    p = getattr(r, 'path', '')",
    "    if not methods or not p.startswith('/api/'):",
    "        continue",
    "    routes.append({'path': p, 'methods': methods})",
    "print(json.dumps(routes))",
  ].join("\n");
  const stdout = execFileSync(python, ["-c", script], {
    cwd: repoRoot,
    encoding: "utf-8",
    // 后端冷启动 import 实测 >120s，原值必然 SIGTERM，整个文件崩溃 ——
    // 这是全仓唯一防「加了后端端点忘登记代理白名单」的机器保护，
    // 它一崩，那条已知坑就是裸奔状态（2026-08-31 体检）。
    timeout: 600_000,
    env: { ...process.env },
  });
  const lines = stdout.trim().split("\n");
  return JSON.parse(lines[lines.length - 1]);
}

// Sample values per path-parameter name. Each entry may offer several
// candidates; a route counts as proxied when ANY candidate combination is
// accepted by the allowlist.
const UUID_SAMPLE = "0b6cdd8a-19f1-4a52-9c3e-2f61a7b0c9d4";
const PARAM_CANDIDATES = {
  default: [
    UUID_SAMPLE,
    "12",
    "org_0123456789abcdef0123456789abcdef",
    "key_0123456789abcdef0123456789abcdef",
    "conv_0123456789abcdef0123456789abcdef",
    "c19frq_0123456789abcdef0123456789abcdef",
    "modules.example.entry",
    "sample",
  ],
};

function candidateValues(paramName) {
  const name = paramName.toLowerCase();
  if (name === "org_id") return ["org_0123456789abcdef0123456789abcdef"];
  if (name === "conversation_id")
    return ["conv_0123456789abcdef0123456789abcdef"];
  if (name === "request_id")
    return ["c19frq_0123456789abcdef0123456789abcdef"];
  if (name === "asset_id")
    return [
      "att_0123456789abcdef0123456789abcdef",
      UUID_SAMPLE,
      "12",
    ];
  if (name === "moment_id")
    return ["mom_0123456789abcdef0123456789abcdef"];
  if (name === "comment_id")
    return ["cmt_0123456789abcdef0123456789abcdef"];
  if (name === "key_id" || name === "binding_id")
    return ["key_0123456789abcdef0123456789abcdef"];
  if (name.endsWith("user_id") || name === "user_id") return ["12", UUID_SAMPLE];
  if (name === "entry_key") return ["modules.example.entry"];
  if (name === "module_id") return ["k.product_knowledge", UUID_SAMPLE, "12"];
  if (name === "game_id") return ["snake"];
  // 内容台的 source 只有两个合法值，代理层就把它卡死（别的段一律 404 在代理）。
  // 灌通用样本的话，严格的白名单会正确地拒绝它，然后这条漂移测试会误报。
  if (name === "source_key") return ["geo", "seo"];
  if (name.endsWith("_id")) return [UUID_SAMPLE, "12"];
  return PARAM_CANDIDATES.default;
}

function expandPathSamples(routePath) {
  // Turn "/api/app/k/products/{product_id}/keywords" into candidate segment
  // arrays with parameters substituted.
  const withoutPrefix = routePath.replace(
    /^\/api\/(?:public|app|control-plane)\//,
    "",
  );
  const segments = withoutPrefix.split("/").filter(Boolean);
  let combos = [[]];
  for (const segment of segments) {
    const match = segment.match(/^\{(.+)\}$/);
    const options = match ? candidateValues(match[1]) : [segment];
    const next = [];
    for (const combo of combos) {
      for (const option of options) {
        next.push([...combo, option]);
      }
    }
    combos = next.slice(0, 64);
  }
  return combos;
}

function isProxied(method, routePath) {
  return expandPathSamples(routePath).some((segments) =>
    isAllowedBackendProxyPath(method, segments),
  );
}

const backendRoutes = backendAvailable ? loadBackendRoutes() : [];

test("backend API route table is non-trivial", { skip: skipReason }, () => {
  assert.ok(backendRoutes.length > 50);
});

test("every backend API endpoint is either proxied or explicitly exempted", { skip: skipReason }, () => {
  const missing = [];
  const staleExemptions = [];
  for (const route of backendRoutes) {
    for (const method of route.methods) {
      const key = `${method} ${route.path}`;
      const proxied = isProxied(method, route.path);
      if (KNOWN_UNPROXIED.has(key)) {
        if (proxied) {
          staleExemptions.push(key);
        }
        continue;
      }
      if (!proxied) {
        missing.push(key);
      }
    }
  }
  assert.deepEqual(
    missing,
    [],
    `Backend endpoints missing from the frontend proxy allowlist (register them in route.ts or add a reasoned entry to KNOWN_UNPROXIED):\n${missing.join("\n")}`,
  );
  assert.deepEqual(
    staleExemptions,
    [],
    `KNOWN_UNPROXIED entries that are now proxied (remove them):\n${staleExemptions.join("\n")}`,
  );
});

test("known-unproxied exemptions still exist on the backend", { skip: skipReason }, () => {
  const routeKeys = new Set(
    backendRoutes.flatMap((route) =>
      route.methods.map((method) => `${method} ${route.path}`),
    ),
  );
  const dead = [...KNOWN_UNPROXIED].filter((key) => !routeKeys.has(key));
  assert.deepEqual(
    dead,
    [],
    `KNOWN_UNPROXIED entries no longer present in the backend route table (remove them):\n${dead.join("\n")}`,
  );
});
