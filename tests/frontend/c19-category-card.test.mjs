import assert from "node:assert/strict";
import test from "node:test";

import { parseC19CategoryCard } from "../../frontend/src/modules/c19/c19CategoryCard.ts";
import { parseC19Card } from "../../frontend/src/modules/c19/c19Card.ts";

const CARD = [
  "【类目 #a1b2】Camping Cookware",
  "路径：Sporting Goods > Outdoor Recreation > Camping & Hiking > Camping Cookware",
  "中文：露营炊具",
  "原因：描述是户外炉具加锅具套装,属于露营烹饪器具而非家用厨具。",
  "备选：Portable Cooking Stoves — 若产品主体是炉头",
  "备选：Camp Furniture — 若主体是折叠桌椅",
  "置信：高",
  "⟦category:a1b2⟧",
].join("\n");

test("parses the category card the way the backend renders it", () => {
  const card = parseC19CategoryCard(CARD);
  assert.ok(card);
  assert.equal(card.cardId, "a1b2");
  assert.equal(card.leafName, "Camping Cookware");
  assert.deepEqual(card.path, ["Sporting Goods", "Outdoor Recreation", "Camping & Hiking", "Camping Cookware"]);
  assert.equal(card.nameZh, "露营炊具");
  assert.equal(card.reason, "描述是户外炉具加锅具套装,属于露营烹饪器具而非家用厨具。");
  assert.deepEqual(card.alternates, [
    { name: "Portable Cooking Stoves", reason: "若产品主体是炉头" },
    { name: "Camp Furniture", reason: "若主体是折叠桌椅" },
  ]);
  assert.equal(card.confidence, "高");
  assert.equal(card.preface, "");
});

test("tolerates half-width colons, missing alternates, em-dash placeholder and a preface", () => {
  const card = parseC19CategoryCard(
    ["先说结论。", "【类目 #0f0f】Thermoses", "路径:Home & Garden > Kitchen & Dining > Thermoses", "中文:—", "置信:中", "⟦category:0f0f⟧"].join("\n"),
  );
  assert.ok(card);
  assert.equal(card.preface, "先说结论。");
  assert.equal(card.leafName, "Thermoses");
  assert.equal(card.nameZh, "");
  assert.deepEqual(card.alternates, []);
  assert.equal(card.reason, "");
  assert.equal(card.confidence, "中");
});

test("rejects plain text, mismatched ids, missing marker, and never collides with the confirm card", () => {
  assert.equal(parseC19CategoryCard("没接通脑子,这句我没处理。"), null);
  assert.equal(parseC19CategoryCard(CARD.replace("⟦category:a1b2⟧", "⟦category:0000⟧")), null);
  assert.equal(parseC19CategoryCard(CARD.replace("⟦category:a1b2⟧", "")), null);
  assert.equal(parseC19CategoryCard(null), null);
  // 两种卡互不相认:待确认卡的解析器看不懂类目卡,反过来也一样。
  assert.equal(parseC19Card(CARD), null);
  const confirmCard = "【待确认 #cc5b】入库\n  TBL-LEG 桌腿 +100 条\n⟦card:cc5b⟧";
  assert.equal(parseC19CategoryCard(confirmCard), null);
});
