// 她的登录浏览器(10-28):画面坐标换算、点/拖判断、键名映射;代理白名单放行了新接口;面板接进了办公室窗口和提醒卡。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";
import { BROWSER_STATUS_LABEL, LIVE_STATUSES, VIEWPORT, isClick, isPrintable, keyFor, toViewport } from "../../frontend/src/components/suqinghe/browser-input.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(path.join(here, "..", "..", rel), "utf8");

test("画面按比例缩放显示:点击位置换算回 1366×900 的视口坐标,画面外不发", () => {
  const rect = { left: 100, top: 50, width: 683, height: 450 }; // 正好一半
  assert.deepEqual(toViewport(100, 50, rect), { x: 0, y: 0 });
  assert.deepEqual(toViewport(783, 500, rect), { x: 1366, y: 900 });
  assert.deepEqual(toViewport(441.5, 275, rect), { x: 683, y: 450 });
  assert.equal(toViewport(99, 50, rect), null);
  assert.equal(toViewport(100, 501, rect), null);
  assert.equal(toViewport(10, 10, { left: 0, top: 0, width: 0, height: 0 }), null);
  assert.equal(VIEWPORT.width, 1366);
});

test("按下抬起离得近是一下点击,远了是拖(滑块);键盘:可打印走 type,功能键按白名单映射", () => {
  assert.equal(isClick({ x: 10, y: 10 }, { x: 12, y: 11 }), true);
  assert.equal(isClick({ x: 10, y: 10 }, { x: 40, y: 10 }), false);
  assert.equal(keyFor("Enter"), "Enter");
  assert.equal(keyFor(" "), "Space");
  assert.equal(keyFor("ArrowLeft"), "ArrowLeft");
  assert.equal(keyFor("F12"), null);
  assert.equal(keyFor("a"), null);
  assert.equal(isPrintable("a"), true);
  assert.equal(isPrintable(" "), false);
  assert.equal(isPrintable("Enter"), false);
  assert.deepEqual(LIVE_STATUSES, ["needs_human", "interactive", "asking_seller"]);
  assert.match(BROWSER_STATUS_LABEL.needs_human, /验证/);
});

test("代理白名单:浏览器状态/画面谁都能看,动作/登录/关掉只放行路径(闸在后端 owner)", () => {
  assert.equal(isAllowedBackendProxyPath("GET", ["suqinghe", "browser"]), true);
  assert.equal(isAllowedBackendProxyPath("GET", ["suqinghe", "browser", "frame"]), true);
  assert.equal(isAllowedBackendProxyPath("GET", ["suqinghe", "browser", "input"]), false);
  assert.equal(isAllowedBackendProxyPath("POST", ["suqinghe", "browser", "input"]), true);
  assert.equal(isAllowedBackendProxyPath("POST", ["suqinghe", "browser", "login"]), true);
  assert.equal(isAllowedBackendProxyPath("POST", ["suqinghe", "browser", "close"]), true);
  assert.equal(isAllowedBackendProxyPath("POST", ["suqinghe", "browser", "frame"]), false);
  assert.equal(isAllowedBackendProxyPath("POST", ["suqinghe", "browser"]), false);
  assert.equal(isAllowedBackendProxyPath("DELETE", ["suqinghe", "browser", "input"]), false);
});

test("面板接进办公室窗口(两种视图都能开)、提醒卡上有「打开浏览器」、档案状态多了「等你过验证」", () => {
  const window = read("frontend/src/components/suqinghe/OfficeWindow.tsx");
  assert.match(window, /<BrowserPanelContext\.Provider value=\{browserControls\}>/);
  assert.match(window, /\{browserOpen \? <BrowserPanel canCommand=\{canCommand\} onClose=/);
  assert.match(window, /className=\{styles\.browserButton\}/);
  const parts = read("frontend/src/components/suqinghe/OfficeParts.tsx");
  assert.match(parts, /evidenceWantsBrowser\(card\.evidence\)/);
  assert.match(parts, /打开浏览器,帮她过验证 →/);
  const api = read("frontend/src/components/suqinghe/office-api.ts");
  assert.match(api, /needs_human: "等你过验证"/);
  assert.match(api, /browser\/frame\?t=/);
  const panel = read("frontend/src/components/suqinghe/BrowserPanel.tsx");
  assert.match(panel, /getBrowser\(true\)/); // 开着面板才告诉 worker「有人在看」
  assert.match(panel, /登录 1688/);
  assert.match(panel, /原尺寸\(扫码用\)/); // 10-28 扫码扫不上:能切到 1366 原尺寸
  assert.match(panel, /data-zoom=\{zoom \? "1" : undefined\}/);
  assert.match(panel, /addEventListener\("wheel", onWheel, \{ passive: false \}\)/); // 10-29 滚轮要拦得住控制台页面
  assert.doesNotMatch(panel, /onWheel=\{/);
  assert.match(panel, /sendBrowserInput\("navigate", \{ url \}\)/); // 10-29 登录后地址栏开商品页
  assert.match(panel, /贴一条 1688 商品页地址/);
  const css = read("frontend/src/components/suqinghe/Office.module.css");
  assert.match(css, /\.browserOverlay \{/);
  assert.match(css, /\.browserFrame \{/);
  assert.match(css, /\.browserStage\[data-zoom="1"\] \.browserFrame \{[^}]*width: 1366px/);
});
