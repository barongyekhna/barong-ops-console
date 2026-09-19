import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import test from "node:test";

const dir = new URL("../../frontend/src/modules/amz/", import.meta.url);
const read = (name) => readFileSync(new URL(name, dir), "utf8");
const sources = readdirSync(dir).filter((name) => /\.(tsx?|css)$/.test(name)).map((name) => [name, read(name)]);

test("员工性格不上前端:amz 模块里没有 character 字段,也没有性格描述", () => {
  // 性格只在后端 persona.py 给模型用(用户 2026-09-19 拍板)
  const traits = ["活泼可爱", "沉稳", "粗中有细", "靠谱大哥哥", "温柔大姐姐", "邻家女孩"];
  for (const [name, source] of sources) {
    assert.ok(!/\.character\b|character\?:|character:/.test(source), `${name} 还在用 character`);
    for (const word of traits) assert.ok(!source.includes(word), `${name} 里出现了性格词「${word}」`);
  }
  const card = readFileSync(new URL("../../frontend/src/components/home/cards/AmzAgents.tsx", import.meta.url), "utf8");
  assert.ok(!card.includes("四人在岗") && !card.includes("4 - stale"), "首页员工卡不能写死四个人");
});

test("员工浮窗:内容区自己滚动(外框固定一屏高),按店分栏可折叠", () => {
  const css = read("AmzOverview.module.css");
  const drawer = css.slice(css.indexOf(".drawer {"), css.indexOf("}", css.indexOf(".drawer {")));
  assert.match(drawer, /overflow-y:\s*auto/);
  assert.match(drawer, /min-height:\s*0/);
  const tsx = read("AmzOverview.tsx");
  assert.ok(tsx.includes("storeGroupHead") && tsx.includes("amz-drawer-folds:"));
  assert.ok(tsx.includes("E: styles.toneE") && css.includes(".toneE"));
});

test("财务 tab 与代理白名单", () => {
  assert.ok(read("AmzPage.tsx").includes('key: "finance"'));
  const route = readFileSync(new URL("../../frontend/src/app/api/backend/[...path]/route.ts", import.meta.url), "utf8");
  assert.ok(route.includes('path[1] === "finance"') && route.includes('path[2] === "costs"'));
});
