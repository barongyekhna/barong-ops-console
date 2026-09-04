// K 产品档案：同级面板的 key 不允许重复。
// 2026-09-04 事故：ProductDetail 拆分后四个兄弟面板都用 key={产品 id}，
// React 19 生产版对同级重复 key 的处理是「有的复制、有的丢掉」，页面上出现两份
// 「关键词审核」、图片区变成不响应的僵尸副本。类型检查和构建都抓不到。
// 这里只断言「同一文件里的 key 表达式两两不同」这一个不变量，不断言内容。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const here = path.dirname(fileURLToPath(import.meta.url));
const target = path.resolve(
  here,
  "../../frontend/src/modules/k/product-knowledge/ProductDetail.tsx",
);

function collectKeyExpressions(source) {
  // 去掉 JSX 注释块，注释里可以随便举例。
  const stripped = source.replace(/\{\/\*[\s\S]*?\*\/\}/g, "");
  const keys = [];
  const pattern = /\bkey=\{((?:[^{}]|\{[^{}]*\})*)\}/g;
  let match;
  while ((match = pattern.exec(stripped)) !== null) {
    keys.push(match[1].trim());
  }
  return keys;
}

test("ProductDetail 同级面板的 key 表达式两两不同", () => {
  const source = readFileSync(target, "utf8");
  const keys = collectKeyExpressions(source);
  assert.ok(keys.length >= 4, `应至少找到四个面板 key，实际 ${keys.length}`);
  const seen = new Map();
  for (const key of keys) {
    seen.set(key, (seen.get(key) ?? 0) + 1);
  }
  const duplicates = [...seen].filter(([, count]) => count > 1).map(([k]) => k);
  assert.deepEqual(
    duplicates,
    [],
    `重复的 key 表达式：${duplicates.join(", ")}（同级同 key 会产生僵尸 DOM）`,
  );
});
