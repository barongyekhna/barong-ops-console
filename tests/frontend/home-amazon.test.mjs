import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (relative) =>
  readFileSync(new URL(`../../frontend/src/${relative}`, import.meta.url), "utf8");

test("amazon registry lists the three A0 cards in order with backend module keys", () => {
  const source = read("components/home/home-registry-amazon.tsx");
  const ids = [...source.matchAll(/^\s+id: "([a-z0-9-]+)",$/gm)].map((match) => match[1]);
  assert.deepEqual(ids, ["amz-stores", "amz-agents", "approvals"]);
  const moduleKeys = [...source.matchAll(/module_key: (null|"[a-z0-9_.]+"),/g)].map((match) => match[1]);
  assert.deepEqual(moduleKeys, ['"amz.ops"', "null", "null"]);
  assert.equal((source.match(/wide: true/g) ?? []).length, 1);
});

test("amazon home reuses the shared shell with its own storage key and skin class", () => {
  const amazon = read("components/home/AmazonHome.tsx");
  assert.ok(amazon.includes("barong-home-cards-v2:amazon"));
  assert.ok(amazon.includes('extraClass="home-amazon"'));
  assert.ok(amazon.includes("<HomeShell"));
});

test("dispatcher routes amazon organizations to AmazonHome after factory and before the legacy fallback", () => {
  const dashboard = read("components/operations-dashboard.tsx");
  assert.ok(dashboard.includes('bootstrap.org_type === "amazon" && bootstrap.cards.length > 0'));
  assert.ok(dashboard.includes("<AmazonHome bootstrap={bootstrap} />"));
  assert.ok(dashboard.indexOf("<FactoryHome bootstrap={bootstrap} />") < dashboard.indexOf("<AmazonHome bootstrap={bootstrap} />"));
  assert.ok(dashboard.indexOf("<AmazonHome bootstrap={bootstrap} />") < dashboard.indexOf("<LegacyOperationsDashboard />"));
});

test("amz module is wired: sidebar prefix, navigation, proxy allowlist, org label, key types", () => {
  const sidebar = read("components/capability-sidebar-engine.tsx");
  assert.match(sidebar, /"amz\.",/);
  // 王创鑫主组织是深圳,但他是四家亚马逊公司的成员:组织树过滤必须认成员集合。
  assert.ok(sidebar.includes("memberOrgIds?.has(organization.org_id)"));
  assert.ok(sidebar.includes('apiRequest<{ organizations?: { org_id: string }[] }>("/auth/organizations")'));
  const nav = read("lib/navigation.ts");
  assert.ok(nav.includes('module_key: "amz.ops"') && nav.includes('href: "/amz"'));
  const proxy = read("app/api/backend/[...path]/route.ts");
  assert.ok(proxy.includes("function isAllowedAmzPath(") && proxy.includes("isAllowedAmzPath(method, path) ||"));
  assert.ok(read("components/org-switcher.tsx").includes('amazon: "亚马逊"'));
  const keyTypes = read("modules/keys/key-types.ts");
  assert.ok(keyTypes.includes('type: "amazon_sp_api"') && keyTypes.includes('type: "amazon_ads_api"'));
});
