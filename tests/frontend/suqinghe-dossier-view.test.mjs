// 档案柜详情(10-26):用真档案喂「草稿 → 界面」那一层。
//
// 起因:界面把 draft 最外层的每个键都当一行字段,嵌套对象被压平成一墙「键：值；键：值」;
// 变体表取的字段名和后端存的对不上,只剩重量一列有数(电池那单,老板原话「看不懂」「明显不合格」)。
// 两边各自的测试都是绿的 —— 中间这一层没人测。这里拿线上真实的旧档案(v1)和按新规则生成的档案(v2)喂进去。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { buildDossierView, displayValue } from "../../frontend/src/components/suqinghe/dossier-view.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const load = (name) => JSON.parse(readFileSync(path.join(here, "fixtures", "suqinghe", name), "utf8"));

const v1Battery = load("dossier-v1-643348607768.json");
const battery = load("dossier-v2-643348607768.json");
const lamp = load("dossier-v2-773137484620.json");
const drill = load("dossier-v2-888786557113.json");

/** 界面上会出现的所有字符串 */
function allText(view) {
  const rows = [...view.attention, ...view.basics, ...view.specs];
  return [
    view.summary,
    view.pricing.text,
    view.reading.text,
    view.reading.problem ?? "",
    view.reading.ignored ?? "",
    ...rows.flatMap((r) => [
      r.label,
      r.value,
      r.note,
      ...r.sources.flatMap((s) => [s.where, s.raw]),
      ...r.candidates.flatMap((c) => [c.value, ...c.sources.map((s) => s.raw)]),
      ...r.alternatives.map((a) => a.value),
    ]),
    ...view.variants.flatMap((v) => Object.values(v).map(String)),
    ...view.otherAttributes.flatMap((a) => [a.name, a.value]),
  ];
}

for (const [name, draft] of [["v1 电池", v1Battery], ["v2 电池", battery], ["v2 灭蚊灯", lamp], ["v2 电钻", drill]]) {
  test(`${name}:不摊原始结构、不出内部记号`, () => {
    const view = buildDossierView(draft);
    for (const line of allText(view)) {
      assert.ok(!line.includes("[object Object]"), line);
      assert.ok(!/[{}]/.test(line), `像是原始结构:${line}`);
      assert.ok(!/\b(status|sources|value|unit|note|google_category_id|segment_index)\b/.test(line), `内部字段名漏到界面:${line}`);
    }
    const labels = [...view.basics, ...view.specs].map((r) => r.label);
    for (const internal of ["fields", "specs", "flagged", "version", "offer_id", "image_read", "summary_zh", "flagged_count"]) {
      assert.ok(!labels.includes(internal), `顶层键「${internal}」不该当成一行字段`);
    }
  });
}

test("v1 旧档案:变体表每一列都有数(之前只有重量)", () => {
  const view = buildDossierView(v1Battery);
  assert.equal(view.version, 1);
  assert.equal(view.variants.length, 5);
  const first = view.variants[0];
  assert.equal(first.nameZh, "2000mah");
  assert.equal(first.nameEn, "2000mAh");
  assert.equal(first.packWeight, "170 g");
  assert.equal(first.packDims, "13×9×8 cm");
  // 旧档案抓取时没拿到每个规格的进价 —— 显示「—」,不编
  assert.equal(first.cost, "—");
  assert.ok(view.basics.find((r) => r.key === "category").value.includes("Power Tool Batteries"));
  assert.ok(view.attention.length >= 1 && view.attention[0].status === "conflict");
});

test("v2 电池:按规格的进价、容量,标红只有该标的", () => {
  const view = buildDossierView(battery);
  assert.equal(view.version, 2);
  const byName = Object.fromEntries(view.variants.map((v) => [v.nameZh, v]));
  assert.equal(byName["1300mah"].cost, "¥16.99");
  assert.equal(byName["2500mah"].cost, "¥49");
  assert.equal(byName["12V直充充电器"].cost, "¥9");
  assert.equal(byName["2000mah"].specs, "2000mAh");
  assert.equal(view.pricing.text, "按规格 ¥9–¥49");

  const spec = Object.fromEntries(view.specs.map((r) => [r.key, r]));
  assert.equal(spec["specs.voltage"].value, "12 V");
  assert.equal(spec["specs.dimensions"].value, "84×48×40 mm");
  assert.equal(spec["specs.weight"].value, "166 g");
  assert.equal(spec["specs.capacity"].value, "1300mAh / 1500mAh / 2000mAh / 2500mAh");
  assert.equal(spec["specs.capacity"].perVariant.length, 4);
  assert.ok(view.specs.every((r) => r.status === "ok"), "电池这单没有真矛盾");

  assert.deepEqual(view.attention.map((r) => r.label), ["美国售价", "包装清单"]);
  assert.ok(view.reading.ignored.includes("别的商品 7 条"));
  assert.equal(view.supplier.name, "湖南来美电子科技有限公司");
  assert.ok(view.supplier.detail.includes("工厂"));
});

test("v2 灭蚊灯:真矛盾排最前,各方说法和出处都在", () => {
  const view = buildDossierView(lamp);
  assert.deepEqual(
    view.attention.map((r) => [r.label, r.status]),
    [["材质", "conflict"], ["容量", "conflict"], ["美国售价", "needs_owner"]],
  );
  const material = view.attention[0];
  assert.deepEqual(material.candidates.map((c) => c.value), ["铝合金", "尼龙+PS"]);
  assert.ok(material.candidates[1].sources[0].where.startsWith("详情图"));
  const capacity = view.attention[1];
  assert.deepEqual(capacity.candidates.map((c) => c.value), ["1200", "3000 mAh"]);
  assert.deepEqual(capacity.alternatives.map((a) => a.value), ["1500 mAh"]);

  const spec = Object.fromEntries(view.specs.map((r) => [r.key, r]));
  assert.equal(spec["specs.dimensions"].value, "153×40×40 mm");
  assert.equal(spec["specs.dimensions_pack"].value, "186×110×45 mm");
  assert.equal(spec["specs.dimensions_pack"].label, "尺寸(单个包装)");
  assert.equal(spec["specs.weight_pack"].value, "256.2 g");
  assert.equal(spec["specs.color"].value, "黑色、绿色");
  assert.equal(view.basics.find((r) => r.key === "package_includes").value, "Tripod stand、USB-C charging cable");
});

test("v2 电钻:电压两种说法要老板选,「咨询客服」是没找到", () => {
  const view = buildDossierView(drill);
  const voltage = view.attention.find((r) => r.label === "电压");
  assert.equal(voltage.status, "conflict");
  assert.deepEqual(new Set(voltage.candidates.map((c) => c.value)), new Set(["交流220 V", "12 V"]));
  const dims = view.attention.find((r) => r.label === "尺寸(单品)");
  assert.equal(dims.status, "missing");
  assert.ok(dims.note.includes("咨询客服"));
  const byName = Object.fromEntries(view.variants.map((v) => [v.nameZh, v.cost]));
  assert.deepEqual(byName, { 两电一充套装: "¥76", 裸机: "¥36", 一电一充套装: "¥66" });
});

test("displayValue:认不出的对象显示「—」,单位不重复", () => {
  assert.equal(displayValue({ a: { b: 1 } }), "—");
  assert.equal(displayValue("12V", "V"), "12V");
  assert.equal(displayValue("12", "V"), "12 V");
  assert.equal(displayValue(["A", null, "B"]), "A、B");
  assert.equal(
    displayValue({ google_category_id: "1", name: "Toys", path: "Toys & Games > Toys", name_zh: "玩具", confidence: "low" }),
    "玩具 · Toys & Games > Toys(把握:低)",
  );
});

test("读图出问题要说出来", () => {
  const view = buildDossierView({ image_read: { detail_error: "详情图清单取了 3 次都没取到(TimeoutError)" } });
  assert.equal(view.reading.text, "详情图没取到,规格只来自页面数据");
  assert.ok(view.reading.problem.includes("3 次"));
  const budget = buildDossierView({ image_read: { images: 19, segments_seen: 9, stopped_reason: "budget", images_failed: 1 } });
  assert.equal(budget.reading.text, "详情图 19 张,读了 9 段,1 张打不开");
  assert.ok(budget.reading.problem.includes("预算"));
  // 扔掉的读图结果要说出条数(10-26 电钻:续航读成「25%」)
  const unit = buildDossierView({ image_read: { images: 11, segments_seen: 16, ignored_other: 1, ignored_unit: 2 } });
  assert.equal(unit.reading.ignored, "已排除:别的商品 1 条、单位对不上 2 条");
});
