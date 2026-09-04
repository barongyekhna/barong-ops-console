import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// 2026-09-04 用户报的两个回归，钉成契约：
//  1) 顶栏/侧栏 logo 回主页必须直奔 /dashboard，不能经过根路由 "/"（客户端导航会落成空白页）
//  2) apiRequest 自己序列化 body，调用方绝不能再 JSON.stringify（会双重编码 → 后端 422）
const shell = readFileSync(new URL("../../frontend/src/components/console-shell.tsx", import.meta.url), "utf8");
const raApi = readFileSync(new URL("../../frontend/src/modules/r/analysis/api.ts", import.meta.url), "utf8");
const libApi = readFileSync(new URL("../../frontend/src/lib/api.ts", import.meta.url), "utf8");

test("logo click navigates straight to /dashboard, never to the bare root", () => {
  const handler = shell.slice(shell.indexOf("function handleLogoClick"), shell.indexOf("}", shell.indexOf("function handleLogoClick")));
  assert.match(handler, /router\.push\("\/dashboard"\)/);
  assert.doesNotMatch(handler, /router\.(push|replace)\("\/"\)/);
});

test("apiRequest serialises bodies itself, so callers pass objects (cruise toggle regression)", () => {
  assert.match(libApi, /JSON\.stringify\(body\)/);
  assert.doesNotMatch(raApi, /body:\s*JSON\.stringify\(/);
  assert.match(raApi, /body:\s*\{\s*paused\s*\}/);
});
