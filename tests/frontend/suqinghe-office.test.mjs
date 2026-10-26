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
  assert.match(scene, /她只听老板的安排；你也可以和她聊/);
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

test("档案柜:书柜下半的柜门是新热区,和书柜不重叠,打开档案柜面板", () => {
  assert.match(scene, /\{ id: "cabinet", label: "[^"]+", box: \[20\.0, 40\.5, 14\.5, 20\.5\], panel: "cabinet" \}/);
  assert.match(scene, /\{ id: "bookshelf", label: "[^"]+", box: \[17\.9, 10\.9, 17\.7, 29\.0\], panel: "bookshelf" \}/);
  // 书柜底边 10.9+29.0=39.9 < 柜门顶 40.5
  assert.ok(10.9 + 29.0 < 40.5);
  assert.match(scene, /case "cabinet":\s*return <CabinetPanel/);
  assert.match(scene, /cabinet: "🗄 档案柜/);
});

test("档案柜状态都有中文标签;进行中的每 5 秒刷新", () => {
  for (const [key, label] of [
    ["queued", "排队"],
    ["fetching", "在抓页面"],
    ["reading", "在读图"],
    ["ready", "待你批"],
    ["blocked", "被1688拦了"],
    ["failed", "失败"],
    ["created", "已建进K"],
    ["rejected", "已驳回"],
  ]) {
    assert.match(api, new RegExp(`${key}: "${label}"`));
  }
  assert.match(api, /export function submitDossier\(url: string\)/);
  assert.match(api, /`\$\{BASE\}\/dossiers\?limit=\$\{limit\}`/);
  assert.match(scene, /window\.setInterval\(load, 5000\)/);
});

test("丢 1688 链接的输入框只给老板;收件筐里的建档卡能跳到档案", () => {
  const phone = scene.slice(scene.indexOf("function PhonePanel"), scene.indexOf("// ---------------------------------------------------------------- 档案柜"));
  assert.match(phone, /\{canCommand \? \(\s*<details[\s\S]*<DossierLinkForm[\s\S]*<\/details>\s*\) : \(/);
  assert.match(scene, /export function looksLike1688Offer/);
  assert.match(parts, /card\.kind !== "create_k_dossier"/);
  assert.match(parts, /看档案 →/);
  assert.match(scene, /onOpenDossier=\{onOpenDossier\}/);
});

test("档案详情不把原始 JSON 摊出来:只经 dossier-view 读草稿、标红分颜色、老板能重新整理", () => {
  const view = scene.slice(scene.indexOf("function DossierView"));
  assert.ok(!view.includes("JSON.stringify"), "dossier detail must not dump JSON");
  // 草稿 → 界面这一层在 dossier-view.ts(纯函数,suqinghe-dossier-view.test.mjs 用真档案测);组件里不再自己猜字段
  assert.match(view, /buildDossierView\(detail\?\.draft\)/);
  assert.ok(!/draft\.(variants|price_tiers|fields|specs)/.test(view), "组件不该直接翻 draft 的字段");
  for (const status of ["conflict", "missing", "needs_owner"]) {
    assert.match(sceneCss, new RegExp(`\\.fieldRow\\[data-status="${status}"\\]`));
  }
  const dossierView = read("frontend/src/components/suqinghe/dossier-view.ts");
  assert.match(dossierView, /page_json: "页面数据"/);
  assert.match(dossierView, /page_text: "页面文字"/);
  assert.match(scene, /去收件筐批/);
  assert.match(view, /canCommand && REDO_STATUSES\.includes\(detail\.status\)/);
  assert.match(api, /export function redoDossier\(id: number\)/);
  assert.match(api, /\/dossiers\/\$\{encodeURIComponent\(String\(id\)\)\}\/redo`, \{ method: "POST" \}/);
});

test("office phone embeds the C19 private chat with her and pings on new messages", () => {
  const chat = readFileSync(new URL("../../frontend/src/components/suqinghe/OfficeChat.tsx", import.meta.url), "utf8");
  const api = readFileSync(new URL("../../frontend/src/components/suqinghe/office-api.ts", import.meta.url), "utf8");
  const scene = readFileSync(new URL("../../frontend/src/components/suqinghe/OfficeScene.tsx", import.meta.url), "utf8");
  // 同一条 C19 私聊,不另起一套
  assert.match(api, /createC19DirectConversation\(\{ peer_user_id: peer \}\)/);
  assert.match(api, /listC19MessageHistory/);
  assert.match(api, /sendC19Message/);
  assert.match(chat, /和 C19 里的私聊是同一条对话/);
  assert.match(chat, /isComposing/, "Enter 发送时不能打断中文输入法");
  assert.match(scene, /<OfficeChat onSeen=\{onSeen\} \/>/);
  assert.match(scene, /useChatPing\(openPanel === "phone"\)/);
  assert.match(scene, /styles\.phoneDot/);
});


test("批了还在建进 K 的那几秒显示「已批，建档中」,并且继续刷新、不再给批/重新整理按钮", () => {
  assert.match(api, /building\?: boolean;/);
  assert.match(api, /if \(item\.building && item\.status === "ready"\) return \{ key: "building", label: "已批，建档中" \}/);
  assert.match(scene, /data-status=\{dossierStatusOf\(item\)\.key\}/);
  assert.match(scene, /data-status=\{dossierStatusOf\(detail\)\.key\}/);
  assert.match(scene, /DOSSIER_IN_PROGRESS\.includes\(item\.status\) \|\| item\.building/);
  assert.match(scene, /detail\.status === "ready" && !detail\.building/);
  assert.match(scene, /REDO_STATUSES\.includes\(detail\.status\) && !detail\.building/);
  assert.match(sceneCss, /\.dossierStatus\[data-status="building"\]/);
});

test("白板定目标:跟踪的数从下拉里选,只给后端认得的键", () => {
  assert.match(api, /\{ value: "published_products", label: "店里发布的品数" \}/);
  assert.match(parts, /GOAL_METRICS\.map/);
  assert.doesNotMatch(parts, /placeholder="指标"/);
  assert.match(read("backend/app/modules/agent_series/suqinghe/snapshot.py"), /metric\.get\("metric"\) == "published_products"/);
});
