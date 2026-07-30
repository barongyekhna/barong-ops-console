import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// 一单三张纸（PI + 商业发票 + 装箱单）。平铺列表到第四单就是 12 行乱序，
// 得靠单号日期自己拼哪三张是一单的。这几条钉住归堆的规则。
const source = readFileSync(
  path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../../frontend/src/modules/b2b/documents/DocumentsWorkspace.tsx",
  ),
  "utf8",
);

test("CI/PL 按 source_document_id 归到它们的 PI 下", () => {
  assert.match(source, /byPi\.get\(doc\.source_document_id/);
});

test("找不到源单的单据绝不静默丢掉", () => {
  // 那是已经发给买家、报过关的凭证，从界面上消失比留着难看得多
  assert.match(source, /orphans\.push\(doc\)/);
  assert.match(source, /orphans\.length \?/, "孤儿单必须渲染出来");
});

test("默认只看未完成的，已完成的收起来但给出数量", () => {
  assert.match(source, /useState\(true\)/);
  assert.match(source, /stage !== "closed"/);
  assert.match(source, /closedCount/);
});

test("阶段下拉和派生按钮只挂在 PI 上", () => {
  // 商业发票和装箱单是 PI 的派生物，自己没有订单阶段
  const orderBlock = source.slice(source.indexOf("orders.map("));
  assert.ok(
    !orderBlock.includes("paper.stage"),
    "派生单据不该有自己的阶段下拉",
  );
});
