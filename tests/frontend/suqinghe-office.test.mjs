import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (rel) => readFileSync(path.join(repoRoot, rel), "utf8");

const shell = read("frontend/src/components/console-shell.tsx");
const launcher = read("frontend/src/components/suqinghe/OfficeLauncher.tsx");
const windowSource = read("frontend/src/components/suqinghe/OfficeWindow.tsx");
const api = read("frontend/src/components/suqinghe/office-api.ts");
const css = read("frontend/src/components/suqinghe/Office.module.css");

test("苏青禾办公室入口挂在全局外壳里,不进侧边栏", () => {
  assert.match(shell, /import \{ OfficeLauncher \} from "@\/components\/suqinghe\/OfficeLauncher"/);
  assert.match(shell, /<OfficeLauncher \/>/);
  assert.doesNotMatch(read("frontend/src/lib/navigation.ts"), /suqinghe/);
});

test("机器人账号和未登录时不显示入口", () => {
  assert.match(launcher, /status === "authenticated"/);
  assert.match(launcher, /is_bot/);
});

test("五种状态都有中文标签和肖像", () => {
  for (const [state, label] of [
    ["working", "干活"],
    ["thinking", "在想"],
    ["raised", "举手"],
    ["night", "夜班"],
    ["offline", "掉线"],
  ]) {
    assert.match(api, new RegExp(`${state}: "${label}"`));
    assert.match(css, new RegExp(`\\[data-state="${state}"\\]`));
  }
  assert.match(api, /\/assets\/agents\/suqinghe\/\$\{state\}\.webp/);
});

test("指挥她的控件只在 can_command 时出现;其他人只读", () => {
  assert.match(windowSource, /const canCommand = Boolean\(office\?\.can_command\)/);
  assert.match(windowSource, /canCommand \? \(\s*<OwnerControls/);
  assert.match(windowSource, /只有老板能指挥她/);
  assert.match(windowSource, /\{canCommand \? \(\s*rejecting/);
  assert.match(launcher, /office\?\.can_command \? office\.today\.cards_pending : 0/);
});

test("驳回必须先写原因", () => {
  assert.match(windowSource, /if \(!reason\.trim\(\)\) return;/);
  assert.match(windowSource, /disabled=\{busy \|\| !reason\.trim\(\)\}/);
});

test("层级在 OverlayModal(3600)之下,并尊重减少动画", () => {
  assert.match(css, /z-index: 3500;/);
  assert.match(css, /z-index: 3550;/);
  assert.match(css, /prefers-reduced-motion: reduce/);
});

test("代理白名单放行办公室的各个接口,别的形状不放", () => {
  const allowed = (method, p) => isAllowedBackendProxyPath(method, p.split("/").filter(Boolean));
  assert.ok(allowed("GET", "suqinghe/office"));
  assert.ok(allowed("POST", "suqinghe/cards/a3f9/decide"));
  assert.ok(allowed("POST", "suqinghe/goals"));
  assert.ok(allowed("PATCH", "suqinghe/goals/12"));
  assert.ok(allowed("POST", "suqinghe/control"));
  assert.ok(allowed("POST", "suqinghe/instruct"));
  assert.ok(!allowed("DELETE", "suqinghe/goals/12"));
  assert.ok(!allowed("POST", "suqinghe/cards/../decide"));
  assert.ok(!allowed("GET", "suqinghe/memory"));
});
