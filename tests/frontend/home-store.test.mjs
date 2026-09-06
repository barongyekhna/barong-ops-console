import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  getBackendApiPath,
  isAllowedBackendProxyPath,
} from "../../frontend/src/app/api/backend/[...path]/route.ts";

const read = (relative) =>
  readFileSync(new URL(`../../frontend/src/${relative}`, import.meta.url), "utf8");

test("store home endpoints are proxied read-only under /api/app", () => {
  const allowed = [
    ["GET", ["dashboard", "home"]],
    ["GET", ["dashboard", "home", "stream"]],
    ["GET", ["dashboard", "home", "traffic"]],
    ["GET", ["dashboard", "home", "traffic", "range"]],
    ["GET", ["dashboard", "home", "cards", "cs-inbox"]],
    ["GET", ["dashboard", "home", "cards", "site-traffic"]],
  ];
  for (const [method, path] of allowed) {
    assert.equal(isAllowedBackendProxyPath(method, path), true, path.join("/"));
    assert.equal(getBackendApiPath(method, path), `/api/app/${path.join("/")}`);
  }

  const denied = [
    ["POST", ["dashboard", "home"]],
    ["POST", ["dashboard", "home", "stream"]],
    ["GET", ["dashboard", "home", "cards", "../x"]],
    ["GET", ["dashboard", "home", "cards", "CS_INBOX"]],
    ["GET", ["dashboard", "home", "traffic", "other"]],
    ["GET", ["dashboard", "home", "nope"]],
    ["POST", ["w", "traffic", "ingest"]],
    ["GET", ["w", "traffic", "ingest"]],
  ];
  for (const [method, path] of denied) {
    assert.equal(isAllowedBackendProxyPath(method, path), false, `${method} ${path.join("/")}`);
  }
});

test("registry lists the nine design cards in order with backend module keys", () => {
  const source = read("components/home/home-registry.tsx");
  const ids = [...source.matchAll(/^\s+id: "([a-z0-9-]+)",$/gm)].map((match) => match[1]);
  assert.deepEqual(ids, [
    "site-traffic",
    "site-health",
    "cs-inbox",
    "w-orders",
    "geo-todo",
    "seo-todo",
    "b2b-drafts",
    "sm-todo",
    "approvals",
  ]);
  const moduleKeys = [...source.matchAll(/module_key: (null|"[a-z0-9_.]+"),/g)].map((match) => match[1]);
  assert.deepEqual(moduleKeys, [
    "null",
    "null",
    '"cs.customer_service"',
    '"w.site_ops"',
    '"geo.content"',
    '"seo.content"',
    '"b2b.wholesale"',
    '"sm.social"',
    "null",
  ]);
  // 流量卡占两列，且只有它占两列
  assert.equal((source.match(/wide: true/g) ?? []).length, 1);
  assert.ok(source.indexOf('id: "site-traffic"') < source.indexOf("wide: true"));
});

test("store home keeps the scene first, the arcade after the grid, one stream per tab", () => {
  // 骨架抽到了 HomeShell（贸易/制造两张皮共用）；StoreHome 只剩注册表 + 存储键。
  const home = read("components/home/HomeShell.tsx");
  assert.ok(home.includes("<DashboardScene />"));
  assert.ok(home.indexOf("<DashboardScene />") < home.indexOf('className="cc-head"'));
  assert.ok(home.includes("<ConsoleArcade />"));
  assert.ok(home.indexOf("cc-grid") < home.indexOf("<ConsoleArcade />"));
  assert.ok(home.indexOf("<ConsoleArcade />") < home.indexOf("<OverlayModal"));
  assert.ok(home.includes('placement="drawer"'));
  const store = read("components/home/StoreHome.tsx");
  assert.ok(store.includes("barong-home-cards-v2:store"));
  assert.ok(!store.includes("barong-dash-cards-v1"));
  assert.ok(store.includes("<HomeShell"));

  const stream = read("components/home/useHomeStream.ts");
  assert.ok(stream.includes("withCredentials: true"));
  assert.ok(stream.includes("c19SseReconnectDelay"));
  assert.ok(stream.includes('addEventListener("card"'));
  assert.ok(stream.includes('addEventListener("card-removed"'));
  const api = read("components/home/home-api.ts");
  assert.ok(api.includes('"/api/backend/dashboard/home/stream"'));
});

test("legacy dashboard stays intact for non-store organizations", () => {
  const dashboard = read("components/operations-dashboard.tsx");
  assert.ok(dashboard.includes("export function OperationsDashboard()"));
  assert.ok(dashboard.includes("export function LegacyOperationsDashboard()"));
  assert.ok(dashboard.includes('bootstrap.org_type === "store"'));
  assert.ok(dashboard.includes("<ConsoleArcade />"));
  assert.ok(dashboard.includes("<DashboardScene />"));
  assert.ok(dashboard.includes('"barong-dash-cards-v1"'));

  const page = read("app/(console)/dashboard/page.tsx");
  assert.ok(page.includes("<OperationsDashboard />"));
});

test("B2B drawer never exposes a send action", () => {
  const b2b = read("components/home/cards/B2bDrafts.tsx");
  assert.ok(!b2b.includes('status: "sent"'));
  assert.ok(!/sendDraft|发送草稿|立即发送/.test(b2b));
  assert.ok(b2b.includes('status: "skipped"'));
});

test("store home CSS layer is registered and uses tokens only", () => {
  const css = read("app/globals.css");
  // 层目录是文件里第一个 ===== 块；第二个 ===== 块起就是真正的样式层。
  const directoryEnd = css.indexOf("/* ====", 5);
  assert.ok(css.slice(0, directoryEnd).includes("STORE HOME"));
  const layerStart = css.lastIndexOf("STORE HOME · 贸易公司主页八卡");
  assert.ok(layerStart > directoryEnd);
  const layer = css.slice(layerStart);
  assert.equal((layer.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []).length, 0, "no hex literals in the layer");
  assert.ok(!/rgba?\(\s*\d/.test(layer), "no rgb literals in the layer");
  for (const line of layer.split("\n")) {
    if (line.startsWith(".") || line.startsWith("@keyframes")) {
      assert.ok(line.startsWith(".home-store") || line.startsWith("@keyframes hsPulse"), line.slice(0, 60));
    }
  }
});
