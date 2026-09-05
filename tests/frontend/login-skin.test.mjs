import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// 2026-09-04 登录页随三皮肤（方案 A）钉成契约：
//  - 样式零颜色字面量走令牌（装饰变量 --lg-* 除外，它们是登录页自己的六套皮）
//  - 六个 皮肤×明暗 组合各有定义，跟随系统靠 @media
//  - 龙鳞是 mask，一张图三种颜色；凤凰仍是原厂 phoenix-gold.png（家规）
const css = readFileSync(new URL("../../frontend/src/components/login.module.css", import.meta.url), "utf8");
const screen = readFileSync(new URL("../../frontend/src/components/login-screen.tsx", import.meta.url), "utf8");
const gate = readFileSync(new URL("../../frontend/scripts/verify-theme-literals.mjs", import.meta.url), "utf8");
const allow = readFileSync(new URL("../../frontend/scripts/theme-audit-allowlist.json", import.meta.url), "utf8");

test("login styles define all six skin×mode decoration blocks plus system-light media", () => {
  for (const sel of [
    'html[data-skin="blush"]) .page',
    'html[data-skin="celadon"]) .page',
    'html[data-mode="light"]) .page',
    'html[data-skin="blush"][data-mode="light"]) .page',
    'html[data-skin="celadon"][data-mode="light"]) .page',
    'html[data-mode="dark"]) .page',
    'html[data-skin="blush"][data-mode="dark"]) .page',
    'html[data-skin="celadon"][data-mode="dark"]) .page',
  ]) assert.ok(css.includes(sel), `missing ${sel}`);
  assert.match(css, /@media \(prefers-color-scheme: light\)/);
  assert.match(css, /html:not\(\[data-skin="blush"\]\):not\(\[data-skin="celadon"\]\):not\(\[data-mode="dark"\]\)\) \.page/);
});

test("login colours come from tokens; literals only inside the --lg-* decoration variables", () => {
  const decls = css.match(/^\s*([-\w]+)\s*:\s*([^;]+);/gm) || [];
  const offenders = decls.filter((d) => {
    const [, prop, value] = d.match(/^\s*([-\w]+)\s*:\s*([^;]+);/);
    if (prop.startsWith("--lg-") || /^(box-shadow|filter)$/.test(prop)) return false;
    if (/^\.dot(Cockpit|Blush|Celadon)/.test(prop)) return false;
    return /#[0-9a-f]{3,8}\b|rgba?\((?!\s*0[,\s]+0[,\s]+0)/i.test(value);
  });
  // 色点是"皮肤预览"、凤凰是名片金色渐变——这两处的字面量是有意的（同设置页的色板）
  const allowed = offenders.filter((d) => !/^\s*background: linear-gradient\(135deg, #/.test(d));
  assert.deepEqual(allowed, []);
  assert.doesNotMatch(css, /^\s*--(line|mono|ink|muted|surface|canvas|signal|accent[\w-]*):/m, "must not shadow global aliases");
});

test("dragon is a recolourable mask; phoenix is the v5 polished-gold original, shown as-is", () => {
  assert.match(css, /\.dragon \{[\s\S]*?mask: url\("\/assets\/brand\/circuit-dragon\.svg"\)/);
  assert.match(screen, /<span className=\{styles\.dragon\} aria-hidden="true" \/>/);
  assert.match(screen, /src="\/assets\/brand\/phoenix-gold-v5\.webp"/);
  assert.doesNotMatch(screen, /phoenix-gold\.png/, "the tightly cropped card raster (no head dots, soft on Retina) is retired on the login page");
  assert.doesNotMatch(css, /barong-phoenix\.svg/, "the login phoenix is not a recoloured mask any more");
  assert.match(screen, /<LoginThemeSwitch \/>/);
});

test("the login page is no longer exempt from the theme gate or the contrast allowlist", () => {
  assert.doesNotMatch(gate, /components\/login\.module\.css/);
  assert.doesNotMatch(allow, /\^\/login/);
});

test("with nothing stored the theme provider follows the system, like the pre-paint script", () => {
  const provider = readFileSync(new URL("../../frontend/src/components/theme-provider.tsx", import.meta.url), "utf8");
  const fn = provider.slice(provider.indexOf("function readStoredMode"), provider.indexOf("\n}\n", provider.indexOf("function readStoredMode")));
  assert.match(fn, /return "system";/);
  assert.equal((fn.match(/return "dark";/g) || []).length, 1, "only the SSR guard may default to dark");
});
