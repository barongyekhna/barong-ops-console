/**
 * M 系列「出货明细卡」的文本格式解析。
 *
 * 这份测试守的是一条契约:卡片正文由后端 backend/app/modules/m_series/cost/card.py
 * 生成,由 frontend/src/modules/c19/c19CostCard.ts 解析。两边任何一边改了行前缀或
 * 字段名,卡片就会静默退化成一段带竖线的纯文本——不报错,只是难看。
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  isCostCardExpired,
  parseC19CostCard,
} from "../../frontend/src/modules/c19/c19CostCard.ts";

const FULL_CARD = [
  "【出货明细 #a1b2】折叠桌 TBL-001 × 100 套",
  "单号：CS-000012",
  "批量：100 套",
  "料|CB-0001|电线|200 米|12.40|0.80|2480.00",
  "料|HW-0007|桌腿|400 条|3.00|0.00|1200.00",
  "工|组装|每件|8.00|800.00",
  "工|调机|每批|1000.00|1000.00",
  "计：物料 3680.00 / 运费 160.00 / 人工 1800.00 / 单位成本 56.40",
  "价：出厂价 88.00 / 单位毛利 31.60 / 毛利率 35.9%",
  "效：2026-09-18（含铜价类波动料）",
  "⟦cost:a1b2⟧",
].join("\n");

const PRICE_ONLY_CARD = [
  "【出货明细 #c3d4】折叠桌 TBL-001 × 100 套",
  "单号：CS-000013",
  "批量：100 套",
  "价：出厂价 88.00",
  "效：2026-10-11",
  "⟦cost:c3d4⟧",
].join("\n");

test("完整明细卡解析出物料、人工和合计", () => {
  const card = parseC19CostCard(FULL_CARD);
  assert.ok(card);
  assert.equal(card.cardId, "a1b2");
  assert.equal(card.sheetNo, "CS-000012");
  assert.equal(card.title, "折叠桌 TBL-001 × 100 套");
  assert.equal(card.materials.length, 2);
  assert.deepEqual(card.materials[0], {
    code: "CB-0001",
    lineTotal: "2480.00",
    name: "电线",
    qty: "200 米",
    unitFreight: "0.80",
    unitPrice: "12.40",
  });
  assert.equal(card.labor.length, 2);
  assert.equal(card.labor[1].mode, "每批");
  assert.match(card.totals, /单位成本 56\.40/);
  assert.equal(card.priceOnly, false);
});

test("仅出厂价的卡片里根本没有成本行", () => {
  const card = parseC19CostCard(PRICE_ONLY_CARD);
  assert.ok(card);
  assert.equal(card.priceOnly, true);
  assert.equal(card.materials.length, 0);
  assert.equal(card.labor.length, 0);
  assert.equal(card.totals, "");
  // 这是这条口径的全部意义:成本数字压根没进过这条消息,
  // 所以对方转发、复制、截图都漏不出去。
  assert.doesNotMatch(PRICE_ONLY_CARD, /成本|毛利/);
  assert.match(card.price, /88\.00/);
});

test("缺价会作为一行明说,而不是让人对着横杠猜", () => {
  const withShortage = FULL_CARD.replace(
    "价：",
    "缺价：3 项，合计不出数\n价：",
  );
  const card = parseC19CostCard(withShortage);
  assert.ok(card);
  assert.match(card.shortage, /3 项/);
});

test("头尾标记对不上就不认这张卡", () => {
  const tampered = FULL_CARD.replace("⟦cost:a1b2⟧", "⟦cost:9999⟧");
  assert.equal(parseC19CostCard(tampered), null);
});

test("普通文本不会被误认成卡片", () => {
  assert.equal(parseC19CostCard("今天出货明细发我一下"), null);
  assert.equal(parseC19CostCard(""), null);
  assert.equal(parseC19CostCard(null), null);
});

test("卡片前面的一句话留在 preface 里", () => {
  const card = parseC19CostCard(`这个报价你看下\n${FULL_CARD}`);
  assert.ok(card);
  assert.equal(card.preface, "这个报价你看下");
});

test("有效期判定认日期,含波动料的后缀不影响", () => {
  const card = parseC19CostCard(FULL_CARD);
  assert.ok(card);
  assert.equal(isCostCardExpired(card, new Date("2026-09-17T10:00:00Z")), false);
  assert.equal(isCostCardExpired(card, new Date("2026-09-20T10:00:00Z")), true);
});

test("解析不出日期时当作没过期,不把好卡片错标成失效", () => {
  const card = parseC19CostCard(FULL_CARD.replace("效：2026-09-18（含铜价类波动料）", "效：长期"));
  assert.ok(card);
  assert.equal(isCostCardExpired(card, new Date("2030-01-01T00:00:00Z")), false);
});
