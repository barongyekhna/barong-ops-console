import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (relative) =>
  readFileSync(new URL(`../../frontend/src/${relative}`, import.meta.url), "utf8");

test("factory registry lists the five design cards in order with backend module keys", () => {
  const source = read("components/home/home-registry-factory.tsx");
  const ids = [...source.matchAll(/^\s+id: "([a-z0-9-]+)",$/gm)].map((match) => match[1]);
  assert.deepEqual(ids, ["mfg-stock", "mfg-capacity", "mfg-docs", "nijing", "approvals"]);
  const moduleKeys = [...source.matchAll(/module_key: (null|"[a-z0-9_.]+"),/g)].map((match) => match[1]);
  assert.deepEqual(moduleKeys, ['"mfg.inventory"', '"mfg.inventory"', '"mfg.inventory"', "null", "null"]);
  assert.equal((source.match(/wide: true/g) ?? []).length, 1);
  assert.ok(source.indexOf('id: "mfg-stock"') < source.indexOf("wide: true"));
});

test("factory home reuses the shared shell with its own storage key and skin class", () => {
  const factory = read("components/home/FactoryHome.tsx");
  assert.ok(factory.includes("barong-home-cards-v2:factory"));
  assert.ok(factory.includes('extraClass="home-factory"'));
  assert.ok(factory.includes("<HomeShell"));

  const store = read("components/home/StoreHome.tsx");
  assert.ok(store.includes("barong-home-cards-v2:store"));
  assert.ok(store.includes("<HomeShell"));
  assert.ok(!store.includes("extraClass"));
});

test("shell keeps the scene first, the arcade after the grid, one drawer scope", () => {
  const shell = read("components/home/HomeShell.tsx");
  assert.ok(shell.includes("<DashboardScene />"));
  assert.ok(shell.indexOf("<DashboardScene />") < shell.indexOf('className="cc-head"'));
  assert.ok(shell.includes("<ConsoleArcade />"));
  assert.ok(shell.indexOf("cc-grid") < shell.indexOf("<ConsoleArcade />"));
  assert.ok(shell.indexOf("<ConsoleArcade />") < shell.indexOf("<OverlayModal"));
  assert.ok(shell.includes('placement="drawer"'));
  // 根节点和浮窗根节点都必须带 home-store 作用域类
  assert.ok(shell.includes('["dashboard-page", "cc-dash", "home-store", extraClass]'));
  assert.ok(shell.includes('["home-store", extraClass, "hs-drawer"]'));
});

test("dispatcher routes factory organizations to FactoryHome and keeps the legacy fallback", () => {
  const dashboard = read("components/operations-dashboard.tsx");
  assert.ok(dashboard.includes('bootstrap.org_type === "factory"'));
  assert.ok(dashboard.includes("<FactoryHome bootstrap={bootstrap} />"));
  assert.ok(dashboard.includes("<LegacyOperationsDashboard />"));
});

test("factory CSS layer is registered, scoped, and token-only", () => {
  const css = read("app/globals.css");
  const directoryEnd = css.indexOf("/* ====", 5);
  assert.ok(css.slice(0, directoryEnd).includes("FACTORY HOME"));
  const layerStart = css.lastIndexOf("FACTORY HOME · 制造公司主页皮肤差异");
  assert.ok(layerStart > directoryEnd);
  const layer = css.slice(layerStart);
  assert.equal((layer.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []).length, 0);
  assert.ok(!/rgba?\(\s*\d/.test(layer));
  for (const line of layer.split("\n")) {
    if (line.startsWith(".")) assert.ok(line.startsWith(".home-store"), line.slice(0, 60));
  }
});
