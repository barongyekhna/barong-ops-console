#!/usr/bin/env node
/**
 * 主题对比度审计 —— 与实现无关的验收尺子。
 *
 * 真浏览器逐路由、逐皮肤、逐明暗遍历所有可见文字，把文字设成透明后截图，
 * 从像素里采样文字所在位置的真实背景色，算 WCAG 对比度。不看 CSS、不信令牌，
 * 只认渲染结果。正文 < 4.5、大字 (≥24px 或 ≥18.66px 粗体) < 3 记失败。
 *
 * 用法：
 *   AUDIT_BASE=http://127.0.0.1:3011 OWNER_USERNAME=… OWNER_PASSWORD=… \
 *   node scripts/theme-contrast-audit.mjs [--skins cockpit,blush,celadon] \
 *     [--modes light,dark,system-light,system-dark] [--routes /dashboard,/users] \
 *     [--out /path/to/dir] [--shots] [--fail-under 4.5]
 *
 * 皮肤/明暗不走设置页按钮（那会 PATCH 用户偏好），而是：
 *   - addInitScript 写 localStorage(barong-theme / barong-skin)，首绘前生效；
 *   - 拦截 GET /api/backend/profile/me 改写 theme_pref / skin_pref，PATCH 直接吞掉，
 *     这样 ProfileProvider 永远拿到审计想要的值，服务端偏好一个字节不动。
 *   - system-* 模式：data-mode 缺省，用 emulateMedia 决定，专门验证手抄的 @media 块。
 *
 * 输出：<out>/report.json（每条失败：route/skin/mode/selector/text/fg/bg/ratio）、
 *       <out>/summary.md，--shots 时另存 <out>/shots/<route>__<skin>-<mode>.png。
 * 退出码：有失败 = 1。
 */
import { chromium } from "playwright";
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { inflateSync } from "node:zlib";

const here = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(here, "..");

// ---------- 参数 ----------
const args = process.argv.slice(2);
function opt(name, fallback) {
  const i = args.indexOf(`--${name}`);
  if (i === -1) return fallback;
  const v = args[i + 1];
  return v && !v.startsWith("--") ? v : true;
}
const BASE = process.env.AUDIT_BASE || "http://127.0.0.1:3011";
const SKINS = String(opt("skins", "cockpit,blush,celadon")).split(",").filter(Boolean);
const MODES = String(opt("modes", "light,dark")).split(",").filter(Boolean);
const OUT = resolve(String(opt("out", process.env.AUDIT_OUT || join(frontendRoot, ".theme-audit"))));
const SHOTS = Boolean(opt("shots", false));
const FAIL_UNDER = Number(opt("fail-under", 4.5));
const LARGE_UNDER = 3.0;
const VIEWPORT_W = 1440;
const MAX_H = 4200; // 超长页整页截图会超时（r-w 仪表盘），折叠区之外的文字多是重复行

// ---------- 路由 ----------
function walk(directory) {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}
function discoverRoutes() {
  const root = join(frontendRoot, "src", "app", "(console)");
  return walk(root)
    .filter((p) => p.endsWith("/page.tsx"))
    .map((p) => p.slice(root.length, -"/page.tsx".length) || "/")
    .filter((r) => !r.includes("["))
    .sort();
}
// 公开路由：未登录审（登录后 PublicOnly 会把 /login 弹回 /dashboard，审不到）
const PUBLIC_ROUTES = ["/login"];
const ROUTES = opt("routes", null) ? String(opt("routes")).split(",") : [...PUBLIC_ROUTES, ...discoverRoutes()];

// ---------- 允许清单 ----------
const allowPath = join(here, "theme-audit-allowlist.json");
const ALLOW = existsSync(allowPath) ? JSON.parse(readFileSync(allowPath, "utf8")) : [];
function allowed(route, selector) {
  return ALLOW.some((rule) => {
    const routeOk = !rule.route || new RegExp(rule.route).test(route);
    const selOk = !rule.selector || new RegExp(rule.selector).test(selector);
    return routeOk && selOk;
  });
}

// ---------- PNG 解码（Chromium 截图：8 位 RGBA/RGB，非隔行） ----------
function decodePng(buf) {
  let pos = 8;
  let width = 0, height = 0, colorType = 6;
  const idat = [];
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos);
    const type = buf.toString("ascii", pos + 4, pos + 8);
    const data = buf.subarray(pos + 8, pos + 8 + len);
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      colorType = data[9];
      if (data[8] !== 8 || data[12] !== 0) throw new Error("unsupported PNG (need 8-bit, non-interlaced)");
    } else if (type === "IDAT") idat.push(data);
    else if (type === "IEND") break;
    pos += 12 + len;
  }
  const bpp = colorType === 6 ? 4 : colorType === 2 ? 3 : (() => { throw new Error("unsupported color type " + colorType); })();
  const raw = inflateSync(Buffer.concat(idat));
  const stride = width * bpp;
  const out = Buffer.alloc(width * height * 4);
  let prev = Buffer.alloc(stride);
  let src = 0;
  for (let y = 0; y < height; y++) {
    const filter = raw[src++];
    const line = Buffer.from(raw.subarray(src, src + stride));
    src += stride;
    for (let i = 0; i < stride; i++) {
      const a = i >= bpp ? line[i - bpp] : 0;
      const b = prev[i];
      const c = i >= bpp ? prev[i - bpp] : 0;
      let v = line[i];
      if (filter === 1) v += a;
      else if (filter === 2) v += b;
      else if (filter === 3) v += (a + b) >> 1;
      else if (filter === 4) {
        const p = a + b - c;
        const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
        v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      }
      line[i] = v & 255;
    }
    for (let x = 0; x < width; x++) {
      const o = (y * width + x) * 4;
      out[o] = line[x * bpp];
      out[o + 1] = line[x * bpp + 1];
      out[o + 2] = line[x * bpp + 2];
      out[o + 3] = bpp === 4 ? line[x * bpp + 3] : 255;
    }
    prev = line;
  }
  return { width, height, data: out };
}

// ---------- 颜色数学 ----------
function lum([r, g, b]) {
  const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function contrast(a, b) {
  const la = lum(a), lb = lum(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}
function over(fg, bg) {
  // fg=[r,g,b,a] 合成到不透明 bg
  const a = fg[3];
  return [0, 1, 2].map((i) => Math.round(fg[i] * a + bg[i] * (1 - a)));
}
const hex = (c) => "#" + c.slice(0, 3).map((v) => v.toString(16).padStart(2, "0")).join("");

// ---------- 页内采集（在浏览器里跑） ----------
const COLLECT = `(() => {
  function parseColor(s) {
    if (!s) return null;
    let m = s.match(/^rgba?\\(\\s*([\\d.]+)[,\\s]+([\\d.]+)[,\\s]+([\\d.]+)(?:[,\\s\\/]+([\\d.]+%?))?\\s*\\)$/);
    if (m) { let a = m[4] === undefined ? 1 : m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]); return [+m[1], +m[2], +m[3], a]; }
    m = s.match(/^color\\(srgb\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)(?:\\s*\\/\\s*([\\d.]+%?))?\\s*\\)$/);
    if (m) { let a = m[4] === undefined ? 1 : m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]); return [Math.round(+m[1]*255), Math.round(+m[2]*255), Math.round(+m[3]*255), a]; }
    return null;
  }
  function pathOf(el) {
    const parts = [];
    let e = el; let depth = 0;
    while (e && e.nodeType === 1 && depth < 4) {
      let s = e.tagName.toLowerCase();
      const cls = Array.from(e.classList).slice(0, 2).join('.');
      if (cls) s += '.' + cls;
      if (e.id) s += '#' + e.id;
      parts.unshift(s); e = e.parentElement; depth++;
    }
    return parts.join(' > ');
  }
  function hidden(el) {
    let e = el;
    while (e && e.nodeType === 1) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) < 0.1) return true;
      if (e.getAttribute('aria-hidden') === 'true') return true;
      if (e.hasAttribute('disabled') || e.getAttribute('aria-disabled') === 'true') return true;
      e = e.parentElement;
    }
    return false;
  }
  function nearestBg(el) {
    let e = el;
    while (e) {
      const cs = getComputedStyle(e);
      const c = parseColor(cs.backgroundColor);
      if (c && c[3] > 0.05) return { color: c, at: pathOf(e), image: cs.backgroundImage !== 'none' };
      e = e.parentElement;
    }
    return null;
  }
  // 绝对/固定定位且自带底色的元素（角标、胶囊、遮罩）会压在别的文字上，
  // 采样点落进去就会把它的底色当成那段文字的背景 —— 先把它们的矩形收集起来排除。
  const overlays = [];
  for (const e of document.querySelectorAll('*')) {
    const cs = getComputedStyle(e);
    if (cs.position !== 'absolute' && cs.position !== 'fixed') continue;
    const c = parseColor(cs.backgroundColor);
    if (!c || c[3] <= 0.05) continue;
    const r = e.getBoundingClientRect();
    // 只认"小块"：整页装饰层（星空底、光晕 ::before）也是绝对定位带底色的，把它们当遮挡会把全站文字筛光。
    if (r.width > 0 && r.height > 0 && r.width * r.height <= 20000) overlays.push({ el: e, r });
  }
  function underOverlay(el, x, y) {
    for (const o of overlays) {
      if (o.el === el || o.el.contains(el)) continue; // 只跳过自己和祖先；后代徽标正是压住父元素文字的那个
      if (x >= o.r.left && x <= o.r.right && y >= o.r.top && y <= o.r.bottom) return true;
    }
    return false;
  }
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const text = node.nodeValue.replace(/\\s+/g, ' ').trim();
    if (!text) continue;
    const el = node.parentElement;
    if (!el || ['SCRIPT','STYLE','NOSCRIPT','TEXTAREA','OPTION'].includes(el.tagName)) continue;
    if (hidden(el)) continue;
    const range = document.createRange(); range.selectNodeContents(node);
    const rects = Array.from(range.getClientRects()).filter(r => r.width > 1 && r.height > 1);
    if (!rects.length) continue;
    const cs = getComputedStyle(el);
    if ((cs.webkitBackgroundClip || cs.backgroundClip) === 'text') continue; // 渐变字：像素法量不到真前景
    const color = parseColor(cs.color);
    if (!color || color[3] < 0.05) continue;
    const fontSize = parseFloat(cs.fontSize);
    const fontWeight = parseInt(cs.fontWeight, 10) || 400;
    const r = rects[0];
    // 采样点：字形框内 3x3，避开边缘 1px
    const pts = [];
    for (const fx of [0.15, 0.5, 0.85]) for (const fy of [0.25, 0.5, 0.75]) {
      const x = r.left + r.width * fx, y = r.top + r.height * fy;
      if (underOverlay(el, x, y)) continue;
      const hit = document.elementFromPoint(x, y);
      if (!hit) continue;
      // 采样点必须真的落在这段文字上：被自带背景的子元素（徽标/胶囊）盖住的点要丢掉，
      // 否则会把徽标底色当成文字背景，算出 1.0x 的假失败。
      let covered = false;
      for (let e = hit; e && e !== el; e = e.parentElement) {
        const c = parseColor(getComputedStyle(e).backgroundColor);
        if (c && c[3] > 0.05) { covered = true; break; }
      }
      if (covered) continue;
      if (hit === el || el.contains(hit) || hit.contains(el)) pts.push([Math.round(x + scrollX), Math.round(y + scrollY)]);
    }
    if (!pts.length) continue; // 被遮挡/在内层滚动区折叠之外
    out.push({ path: pathOf(el), text: text.slice(0, 60), color, fontSize, fontWeight, pts, nearest: nearestBg(el) });
  }
  // 占位符
  for (const inp of document.querySelectorAll('input[placeholder], textarea[placeholder]')) {
    if (inp.value || hidden(inp)) continue;
    const r = inp.getBoundingClientRect(); if (r.width < 2 || r.height < 2) continue;
    const cs = getComputedStyle(inp, '::placeholder');
    const color = parseColor(cs.color); if (!color) continue;
    if (underOverlay(inp, r.left + 12, r.top + r.height / 2)) continue;
    const hit = document.elementFromPoint(r.left + 12, r.top + r.height / 2);
    if (hit !== inp) continue;
    out.push({ path: pathOf(inp) + '::placeholder', text: inp.getAttribute('placeholder').slice(0, 40), color, fontSize: parseFloat(cs.fontSize) || 14, fontWeight: 400,
      pts: [[Math.round(r.left + 12 + scrollX), Math.round(r.top + r.height / 2 + scrollY)], [Math.round(r.left + r.width * 0.4 + scrollX), Math.round(r.top + r.height * 0.3 + scrollY)]], nearest: nearestBg(inp) });
  }
  return out;
})()`;

// 只改「上色」不改「排版」：动画/过渡一旦被 none 掉，带 transform 的面板会瞬移，
// 而文字矩形是注入之前量的 —— 那会让采样点落到页面底色上，报出一堆假失败。
const TRANSPARENT_TEXT = `
  *, *::before, *::after { color: transparent !important; -webkit-text-fill-color: transparent !important;
    caret-color: transparent !important; text-shadow: none !important; text-decoration-color: transparent !important; }
  input::placeholder, textarea::placeholder { color: transparent !important; }
`;

// ---------- 驱动 ----------
async function login(page) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
    if (!/\/login/.test(page.url())) return; // 已有会话，直接被送去了别处
    const inputs = await page.locator("input").all();
    if (inputs.length < 2) throw new Error("login form not found");
    await inputs[0].fill(process.env.OWNER_USERNAME || "");
    await inputs[1].fill(process.env.OWNER_PASSWORD || "");
    await page.locator('button[type="submit"]').first().click();
    try {
      await page.waitForURL((u) => !/\/login/.test(u.pathname), { timeout: 45000 });
      return;
    } catch (e) {
      console.log(`login attempt ${attempt} did not leave /login (${page.url()})`);
      await page.waitForTimeout(3000);
    }
  }
  throw new Error("login failed after 3 attempts");
}

function writeReport(results, started) {
  const failures = results.flatMap((r) => r.failures);
  const errors = results.filter((r) => r.error);
  const report = { base: BASE, generatedAt: new Date().toISOString(), durationMs: Date.now() - started, skins: SKINS, modes: MODES, routes: ROUTES, totals: { pages: results.length, checked: results.reduce((a, r) => a + r.checked, 0), failures: failures.length, errors: errors.length }, results };
  writeFileSync(join(OUT, "report.json"), JSON.stringify(report, null, 2));
  const lines = [`# 主题对比度审计 ${report.generatedAt}`, "", `页面 ${report.totals.pages}，文字节点 ${report.totals.checked}，失败 ${failures.length}，出错 ${errors.length}`, ""];
  const byCombo = {};
  for (const r of results) { const k = `${r.skin}/${r.mode}`; byCombo[k] = (byCombo[k] || 0) + r.failures.length; }
  lines.push("| 组合 | 失败 |", "|---|---|", ...Object.entries(byCombo).map(([k, v]) => `| ${k} | ${v} |`), "");
  const byRoute = {};
  for (const f of failures) byRoute[f.route] = (byRoute[f.route] || 0) + 1;
  lines.push("| 路由 | 失败 |", "|---|---|", ...Object.entries(byRoute).sort((a, b) => b[1] - a[1]).map(([k, v]) => `| ${k} | ${v} |`), "");
  for (const f of failures.slice(0, 600)) lines.push(`- ${f.skin}/${f.mode} ${f.route} ${f.ratio}:1 (需 ${f.need}) fg ${f.fg} on ${f.bg} — \`${f.selector}\` "${f.text}"`);
  for (const e of errors) lines.push(`- ERROR ${e.skin}/${e.mode} ${e.route}: ${e.error}`);
  writeFileSync(join(OUT, "summary.md"), lines.join("\n"));
  return { failures, errors };
}

async function makeContext(browser, skin, mode) {
  const explicit = mode === "light" || mode === "dark";
  const themePref = explicit ? mode : "system";
  const context = await browser.newContext({ viewport: { width: VIEWPORT_W, height: 900 }, colorScheme: mode.endsWith("light") ? "light" : "dark" });
  await context.addInitScript(({ skin, themePref }) => {
    try { localStorage.setItem("barong-skin", skin); localStorage.setItem("barong-theme", themePref); } catch {}
  }, { skin, themePref });
  await context.route("**/api/backend/profile/me", async (route) => {
    const req = route.request();
    if (req.method() === "GET") {
      const res = await route.fetch();
      let body = {};
      try { body = await res.json(); } catch {}
      body.theme_pref = themePref; body.skin_pref = skin;
      await route.fulfill({ response: res, json: body });
    } else {
      // PATCH：吞掉，服务端偏好不动
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ theme_pref: themePref, skin_pref: skin }) });
    }
  });
  return context;
}

async function auditPage(page, route, skin, mode, shotsDir) {
  await page.setViewportSize({ width: VIEWPORT_W, height: 900 });
  await page.goto(`${BASE}${route}`, { waitUntil: "networkidle", timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(1200);
  const finalPath = new URL(page.url()).pathname;
  const docH = await page.evaluate(() => Math.max(document.documentElement.scrollHeight, document.body.scrollHeight));
  const h = Math.min(Math.max(docH, 900), MAX_H);
  await page.setViewportSize({ width: VIEWPORT_W, height: h });
  await page.waitForTimeout(600);
  const attrs = await page.evaluate(() => {
    const rs = getComputedStyle(document.documentElement);
    return {
      skin: document.documentElement.dataset.skin,
      mode: document.documentElement.dataset.mode || "(system)",
      canvas: rs.getPropertyValue("--color-canvas").trim(),
      panel: rs.getPropertyValue("--color-panel-base").trim(),
    };
  });
  // 自检：样式表没生效时页面是"黑字白底"，对比度会全部满分 —— 那是假绿，必须当场炸。
  if (!attrs.canvas || !attrs.panel) throw new Error(`theme tokens missing (--color-canvas="${attrs.canvas}") —— 样式表没加载，结果不可信`);
  if (attrs.skin !== skin) throw new Error(`skin mismatch: 期望 ${skin}，实际 ${attrs.skin}`);
  const wantMode = mode === "light" || mode === "dark" ? mode : "(system)";
  if (attrs.mode !== wantMode) throw new Error(`mode mismatch: 期望 ${wantMode}，实际 ${attrs.mode}`);
  const safe = route.replace(/[^a-z0-9-]+/gi, "_").replace(/^_/, "") || "root";
  if (shotsDir) await page.screenshot({ path: join(shotsDir, `${safe}__${skin}-${mode}.png`), animations: "disabled", caret: "hide", timeout: 60000 });
  const items = await page.evaluate(COLLECT);
  const styleTag = await page.addStyleTag({ content: TRANSPARENT_TEXT });
  await page.waitForTimeout(120);
  const png = decodePng(await page.screenshot({ animations: "disabled", caret: "hide", timeout: 60000 }));
  await styleTag.evaluate((el) => el.remove());
  const failures = [];
  let checked = 0;
  for (const it of items) {
    const samples = it.pts
      .filter(([x, y]) => x >= 0 && y >= 0 && x < png.width && y < png.height)
      .map(([x, y]) => { const o = (y * png.width + x) * 4; return [png.data[o], png.data[o + 1], png.data[o + 2]]; });
    if (!samples.length) continue;
    checked++;
    const large = it.fontSize >= 24 || (it.fontSize >= 18.66 && it.fontWeight >= 700);
    const need = large ? LARGE_UNDER : FAIL_UNDER;
    const scored = samples.map((bg) => ({ bg, c: contrast(it.color[3] < 1 ? over(it.color, bg) : it.color.slice(0, 3), bg) }))
      .sort((a, b) => a.c - b.c);
    // 3 个采样点以上取"次差"：单点常被绝对定位的徽标/胶囊压住，那是采样噪声不是真失败
    const pick = scored.length >= 3 ? scored[1] : scored[0];
    const worst = pick.c, worstBg = pick.bg;
    if (worst < need && !allowed(route, it.path)) {
      failures.push({ route, finalPath, skin, mode, attrs, selector: it.path, text: it.text, fg: hex(it.color), bg: hex(worstBg), ratio: +worst.toFixed(2), need, fontSize: it.fontSize, fontWeight: it.fontWeight, nearestBg: it.nearest ? { color: hex(it.nearest.color), at: it.nearest.at } : null });
    }
  }
  return { route, finalPath, skin, mode, attrs, checked, failures };
}

(async () => {
  mkdirSync(OUT, { recursive: true });
  const shotsDir = SHOTS ? join(OUT, "shots") : null;
  if (shotsDir) mkdirSync(shotsDir, { recursive: true });
  const browser = await chromium.launch();
  const results = [];
  const started = Date.now();
  for (const skin of SKINS) {
    for (const mode of MODES) {
      const context = await makeContext(browser, skin, mode);
      const page = await context.newPage();
      // 先审公开路由（此时还没登录），再登录审控制台
      const publicRoutes = ROUTES.filter((r) => PUBLIC_ROUTES.includes(r));
      const consoleRoutes = ROUTES.filter((r) => !PUBLIC_ROUTES.includes(r));
      for (const route of publicRoutes) {
        try {
          const r = await auditPage(page, route, skin, mode, shotsDir);
          results.push(r);
          console.log(`${skin}/${mode} ${route.padEnd(28)} ${String(r.checked).padStart(4)} texts  ${r.failures.length ? `FAIL ${r.failures.length}` : "ok"}  [${r.attrs.skin}/${r.attrs.mode}] (public)`);
        } catch (e) {
          results.push({ route, skin, mode, error: String(e.message || e).split("\n")[0], failures: [], checked: 0 });
          console.log(`${skin}/${mode} ${route.padEnd(28)} ERROR ${String(e.message || e).split("\n")[0]}`);
        }
      }
      if (!consoleRoutes.length) { await context.close(); writeReport(results, started); continue; }
      try {
        await login(page);
      } catch (e) {
        console.log(`${skin}/${mode} LOGIN ERROR ${e.message}`);
        results.push({ route: "(login)", skin, mode, error: String(e.message || e), failures: [], checked: 0 });
        await context.close();
        continue;
      }
      for (const route of consoleRoutes) {
        try {
          const r = await auditPage(page, route, skin, mode, shotsDir);
          results.push(r);
          const tag = r.failures.length ? `FAIL ${r.failures.length}` : "ok";
          console.log(`${skin}/${mode} ${route.padEnd(28)} ${String(r.checked).padStart(4)} texts  ${tag}  [${r.attrs.skin}/${r.attrs.mode}]`);
        } catch (e) {
          results.push({ route, skin, mode, error: String(e.message || e).split("\n")[0], failures: [], checked: 0 });
          console.log(`${skin}/${mode} ${route.padEnd(28)} ERROR ${String(e.message || e).split("\n")[0]}`);
        }
      }
      await context.close();
      writeReport(results, started);
    }
  }
  await browser.close();
  const { failures, errors } = writeReport(results, started);
  console.log(`\n${failures.length} failures, ${errors.length} errors → ${OUT}/summary.md`);
  process.exit(failures.length || errors.length ? 1 : 0);
})();
