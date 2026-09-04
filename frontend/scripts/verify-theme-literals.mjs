#!/usr/bin/env node
/**
 * 主题字面量闸门 —— 防止浅底浅字/深底深字回潮。
 *
 * 规则（只管模块样式与指定 TSX，globals.css 由令牌引擎自己管）：
 *   1. *.module.css 里不许出现颜色字面量（#hex / rgb() / rgba() / hsl() / 命名色 white），
 *      例外：box-shadow / text-shadow / filter / backdrop-filter 属性内；纯黑 (#000, rgb(0 0 0 …))
 *      任何位置都允许（遮罩、阴影是模式无关的）；transparent / currentColor / inherit 不算字面量。
 *   2. *.module.css 里不许声明全局令牌：--color-* 与遗留别名 --ink --muted --line --surface
 *      --canvas --signal --signal-dark --accent*（CSS Modules 不隔离自定义属性，模块里一声明就
 *      把整棵子树的主题打断——R-W 仓库/K 知识库出过这个事故）。
 *   3. 指定 TSX 文件（style 常量集中的那几份）里不许出现颜色字面量。
 *
 * 逃生口：
 *   - 文件头 `/* theme-literal-ok: file — 原因 *\/`：整个文件跳过（登录页、法务页）。
 *   - 规则前一行 `/* theme-literal-ok: 原因 *\/`：跳过紧随其后的那一条规则块。
 *   - 目录允许清单见下方 SKIP_FILES / SKIP_DIRS（游戏画布、设置页皮肤预览色板）。
 *
 * 退出码：有违规 = 1。`--list` 只打印不报错（迁移期间用来数进度）。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(here, "..");
const srcRoot = join(frontendRoot, "src");
const listOnly = process.argv.includes("--list");

const SKIP_FILES = new Set([
  "components/login.module.css",
  "components/legal-page.module.css",
  "components/legal-content.module.css",
  "components/control-plane-settings-view.tsx", // 皮肤预览色板必须写死
  "components/dashboard-scene.tsx", // canvas 星图
]);
// 游戏画布(components/arcade-*.tsx)与画笔画布(MaskBrush.tsx)不在 TSX_UNDER_GATE 里，天然不查
const SKIP_DIRS = [];
const TSX_UNDER_GATE = [
  "modules/geo/content/GeoContentDeck.tsx",
  "modules/seo/SeoDeck.tsx",
  "modules/seo/facts/CraftFactDeck.tsx",
  "modules/content/LinkNetPanel.tsx",
  "modules/content/SiteNavPanel.tsx",
  "modules/content/ContentHealthPanel.tsx",
  "modules/content/desk/ContentDesk.tsx",
  "modules/content/desk/PublishPanel.tsx",
  "components/mcp-secret-banner.tsx",
  "components/mcp-keys-panel.tsx",
  "components/webhook-registry-panel.tsx",
  "components/permission-route-guard.tsx",
  "modules/r/analysis/RaSubnav.tsx",
  "modules/r/warehouse/WarehouseWorkspace.tsx",
  "modules/k/product-knowledge/ProductForm.tsx",
  "modules/k/product-knowledge/FaqEditorPanel.tsx",
  "modules/k/product-knowledge/RenderImagesPanel.tsx",
  "modules/k/product-knowledge/BrandAuditPanel.tsx",
];

function walk(directory) {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const COLOR_LITERAL = /#[0-9a-f]{3,8}\b|\brgba?\(|\bhsla?\(|\bwhite\b/gi;
const PURE_BLACK = /^(#000(000)?([0-9a-f]{2})?|rgba?\(\s*0[,\s]+0[,\s]+0\b.*)$/i;
const SHADOW_PROPS = /^(box-shadow|text-shadow|filter|backdrop-filter|-webkit-box-shadow)$/i;
const GLOBAL_TOKEN_DECL = /^--(color-[\w-]+|ink|muted|line|surface|canvas|sidebar(-muted)?|signal(-dark)?|warning|accent(-[\w-]+)?|shadow-[\w-]+)$/;

function stripComments(css) {
  // 保留注释里的 theme-literal-ok 标记位置：用等长空白替换其它注释
  return css.replace(/\/\*[\s\S]*?\*\//g, (m) => (/theme-literal-ok/.test(m) ? m : " ".repeat(m.length)));
}

function checkCss(rel, css) {
  const problems = [];
  if (/\/\*\s*theme-literal-ok:\s*file/.test(css)) return problems;
  const text = stripComments(css);
  // 规则级跳过：标记后的第一个 { … } 块
  const skipRanges = [];
  const markerRe = /\/\*\s*theme-literal-ok:[^*]*\*\//g;
  let mm;
  while ((mm = markerRe.exec(text))) {
    const open = text.indexOf("{", mm.index);
    if (open === -1) continue;
    let depth = 0, i = open;
    for (; i < text.length; i++) {
      if (text[i] === "{") depth++;
      else if (text[i] === "}") { depth--; if (depth === 0) break; }
    }
    skipRanges.push([mm.index, i]);
  }
  const skipped = (idx) => skipRanges.some(([a, b]) => idx >= a && idx <= b);
  const lineOf = (idx) => text.slice(0, idx).split("\n").length;

  // 逐声明扫描：property: value;
  const declRe = /([-\w]+)\s*:\s*([^;{}]+)(?=;|\})/g;
  let d;
  while ((d = declRe.exec(text))) {
    const [, prop, value] = d;
    const at = d.index;
    if (skipped(at)) continue;
    if (prop.startsWith("--") && GLOBAL_TOKEN_DECL.test(prop)) {
      problems.push({ file: rel, line: lineOf(at), kind: "global-token-decl", detail: `${prop}: ${value.trim().slice(0, 60)}` });
    }
    if (SHADOW_PROPS.test(prop)) continue;
    // 逐字面量
    const literals = [];
    let m;
    COLOR_LITERAL.lastIndex = 0;
    while ((m = COLOR_LITERAL.exec(value))) {
      let lit = m[0];
      if (lit.endsWith("(")) {
        const close = value.indexOf(")", m.index);
        lit = value.slice(m.index, close + 1);
      }
      if (PURE_BLACK.test(lit.replace(/\s+/g, " "))) continue;
      // url()/data: 里的不算
      const before = value.slice(0, m.index);
      if (/url\([^)]*$/.test(before)) continue;
      literals.push(lit);
    }
    if (literals.length) problems.push({ file: rel, line: lineOf(at), kind: "color-literal", detail: `${prop}: ${literals.join(" ")}` });
  }
  return problems;
}

function checkTsx(rel, src) {
  const problems = [];
  if (/theme-literal-ok:\s*file/.test(src)) return problems;
  const lines = src.split("\n");
  lines.forEach((line, i) => {
    if (/theme-literal-ok/.test(line) || /^\s*\/\//.test(line)) return;
    const hits = line.match(/#[0-9a-f]{6}([0-9a-f]{2})?\b|#[0-9a-f]{3}\b(?![\w-])|\brgba?\([^)]*\)/gi) || [];
    const bad = hits.filter((h) => !PURE_BLACK.test(h));
    if (bad.length) problems.push({ file: rel, line: i + 1, kind: "color-literal", detail: bad.join(" ") });
  });
  return problems;
}

const problems = [];
for (const path of walk(srcRoot)) {
  const rel = relative(srcRoot, path);
  if (SKIP_FILES.has(rel) || SKIP_DIRS.some((d) => rel.startsWith(d + "/"))) continue;
  if (rel.endsWith(".module.css")) problems.push(...checkCss(rel, readFileSync(path, "utf8")));
  else if (TSX_UNDER_GATE.includes(rel)) problems.push(...checkTsx(rel, readFileSync(path, "utf8")));
}

if (problems.length) {
  const byFile = {};
  for (const p of problems) (byFile[p.file] ||= []).push(p);
  for (const [file, list] of Object.entries(byFile).sort((a, b) => b[1].length - a[1].length)) {
    console.log(`${file}: ${list.length}`);
    if (listOnly) for (const p of list.slice(0, 8)) console.log(`   L${p.line} ${p.kind} ${p.detail}`);
  }
  console.log(`\n主题字面量闸门：${problems.length} 处违规，${Object.keys(byFile).length} 个文件。`);
  process.exit(listOnly ? 0 : 1);
}
console.log("主题字面量闸门：通过（模块样式零颜色字面量、零全局令牌重定义）。");
