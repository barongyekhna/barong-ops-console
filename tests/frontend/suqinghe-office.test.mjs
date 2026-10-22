import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (rel) => readFileSync(path.join(repoRoot, rel), "utf8");

const shell = read("frontend/src/components/console-shell.tsx");
const launcher = read("frontend/src/components/suqinghe/OfficeLauncher.tsx");
const windowSource = read("frontend/src/components/suqinghe/OfficeWindow.tsx");
const parts = read("frontend/src/components/suqinghe/OfficeParts.tsx");
const scene = read("frontend/src/components/suqinghe/OfficeScene.tsx");
const sceneCss = read("frontend/src/components/suqinghe/OfficeScene.module.css");
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
  assert.match(parts, /\{canCommand \? \(\s*rejecting/);
  assert.match(launcher, /office\?\.can_command \? office\.today\.cards_pending : 0/);
});

test("驳回必须先写原因", () => {
  assert.match(parts, /if \(!reason\.trim\(\)\) return;/);
  assert.match(parts, /disabled=\{busy \|\| !reason\.trim\(\)\}/);
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
  assert.ok(!allowed("POST", "suqinghe/memory"));
});

test("书柜和日历是只读接口:GET 放行,日期只认 YYYY-MM-DD", () => {
  const allowed = (method, p) => isAllowedBackendProxyPath(method, p.split("/").filter(Boolean));
  assert.ok(allowed("GET", "suqinghe/memory"));
  assert.ok(allowed("GET", "suqinghe/snapshots"));
  assert.ok(allowed("GET", "suqinghe/snapshots/2026-10-22"));
  assert.ok(!allowed("GET", "suqinghe/snapshots/latest"));
  assert.ok(!allowed("GET", "suqinghe/snapshots/2026-10-22/extra"));
  assert.ok(!allowed("POST", "suqinghe/snapshots"));
  assert.ok(!allowed("DELETE", "suqinghe/memory"));
});


test("2.5D 场景:十个热区齐全,能打开面板的八个都有对应面板,猫和她本人是彩蛋", () => {
  const ids = ["door", "bookshelf", "whiteboard", "calendar", "monitor", "inbox", "coffee", "phone", "cat", "suqinghe"];
  for (const id of ids) {
    assert.match(scene, new RegExp(`\\{ id: "${id}", label: "[^"]+", box: \\[[\\d., ]+\\], panel: (null|"${id}") \\}`));
  }
  for (const panel of ["door", "bookshelf", "whiteboard", "calendar", "monitor", "inbox", "coffee", "phone"]) {
    assert.match(scene, new RegExp(`case "${panel}":\\s*return <`));
    assert.match(scene, new RegExp(`${panel}: "`));
  }
  assert.match(scene, /id: "cat", label: "橘猫", box: \[[\d., ]+\], panel: null/);
  assert.match(scene, /id: "suqinghe", label: "苏青禾", box: \[[\d., ]+\], panel: null/);
  assert.match(scene, /<button\s+aria-label=\{spot\.label\}/);
});

test("场景面板里的指挥控件只在 can_command 时出现", () => {
  assert.match(scene, /const canCommand = Boolean\(office\.can_command\)/);
  assert.match(scene, /\{canCommand \? \(\s*<div className=\{partStyles\.inlineActions\}>\s*<PauseButton/);
  assert.match(scene, /\{canCommand \? <GoalForm/);
  assert.match(scene, /只有老板能给她打电话/);
  assert.match(scene, /只有老板能让她暂停或接着干/);
  assert.match(scene, /只有老板能批这些卡/);
});

test("五种状态各有一整幅场景图,动画只跟真实状态走", () => {
  assert.match(scene, /\/assets\/agents\/suqinghe\/office\/scene_\$\{state\}\.webp/);
  for (const state of ["working", "thinking", "raised", "night", "offline"]) {
    assert.ok(existsSync(path.join(repoRoot, `frontend/public/assets/agents/suqinghe/office/scene_${state}.webp`)), state);
    assert.match(scene, new RegExp(`state === "${state}"`));
  }
  assert.match(sceneCss, /\.stage\[data-state="offline"\]/);
  assert.match(sceneCss, /prefers-reduced-motion: reduce/);
  assert.match(sceneCss, /pointer-events: none;/);
});

test("场景/列表可切换,画加载失败自动退回列表", () => {
  assert.match(windowSource, /const showScene = view === "scene" && !sceneFailed/);
  assert.match(windowSource, /onSceneFailed=\{\(\) => setSceneFailed\(true\)\}/);
  assert.match(scene, /onError=\{item === state \? onSceneFailed : undefined\}/);
  assert.match(windowSource, /场景/);
  assert.match(windowSource, /列表/);
  assert.match(windowSource, /放大/);
});

test("calendar snapshot sections render as plain Chinese lines, never raw JSON", () => {
  const scene = readFileSync(new URL("../../frontend/src/components/suqinghe/OfficeScene.tsx", import.meta.url), "utf8");
  assert.match(scene, /export function describeSection/);
  for (const key of ["products", "goals", "content", "approvals", "workers", "keys", "ai"]) {
    assert.ok(scene.includes(`case "${key}"`), `missing describer for ${key}`);
  }
  const snapshotView = scene.slice(scene.indexOf("function SnapshotView"), scene.indexOf("function MonitorPanel"));
  assert.ok(!snapshotView.includes("JSON.stringify"), "SnapshotView must not dump JSON");
  assert.ok(!snapshotView.includes(">其他<"), "the generic 其他 dump section is gone");
});
