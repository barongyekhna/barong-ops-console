import assert from "node:assert/strict";
import test from "node:test";

import { parseC19Card } from "../../frontend/src/modules/c19/c19Card.ts";

const CARD = [
  "【待确认 #cc5b】入库",
  "  TBL-LEG 桌腿  +100 条",
  "  现有 1,300 → 1,400",
  "回「确认」执行,回「取消」作废(30 分钟后自动作废)。",
  "⟦card:cc5b⟧",
].join("\n");

test("parses a bot confirmation card and strips the text-only footer", () => {
  const card = parseC19Card(CARD);
  assert.ok(card);
  assert.equal(card.cardId, "cc5b");
  assert.equal(card.title, "入库");
  assert.deepEqual(card.lines, ["TBL-LEG 桌腿  +100 条", "现有 1,300 → 1,400"]);
  assert.equal(card.preface, "");
});

test("keeps a preface line before the card", () => {
  const card = parseC19Card(`上一张卡 #5809 已作废。\n${CARD}`);
  assert.ok(card);
  assert.equal(card.preface, "上一张卡 #5809 已作废。");
  assert.equal(card.cardId, "cc5b");
});

test("rejects plain text, mismatched ids, and missing markers", () => {
  assert.equal(parseC19Card("已入库 RC-000003。"), null);
  assert.equal(parseC19Card(CARD.replace("⟦card:cc5b⟧", "⟦card:0000⟧")), null);
  assert.equal(parseC19Card(CARD.replace("⟦card:cc5b⟧", "")), null);
  assert.equal(parseC19Card(null), null);
});
