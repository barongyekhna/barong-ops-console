// 苏青禾的卡分七个家族(10-27 卡片重做):kind → 家族/标签/要你做什么,分组排序,每种卡一行基本信息,缩略图地址。
// 夹具是后端真函数生成的(card-*.json),没有的两种(建档、提醒)按后端建卡时的 evidence 形状手写。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { register } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

// card-kinds.ts 相对导入 `./card-view` 不带扩展名,node ESM 不会补,要挂上仓库的解析钩子;静态 import 在钩子挂上前就解析,所以动态 import。
register("./_alias-hooks.mjs", import.meta.url);

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";
const { BLOCKED_CARD_KIND, DOSSIER_CARD_KIND, FAMILIES, FAMILY_ORDER, cardImageUrl, confidenceLabel, familyMeta, familyOf, groupCards, summaryOf, waitedText } = await import(
  "../../frontend/src/components/suqinghe/card-kinds.ts"
);

const here = path.dirname(fileURLToPath(import.meta.url));
const load = (name) => JSON.parse(readFileSync(path.join(here, "fixtures", "suqinghe", name), "utf8"));
const read = (rel) => readFileSync(path.join(here, "..", "..", rel), "utf8");
const price = load("card-price-643348607768.json");
const review = load("card-review-643348607768.json");
const copy = load("card-copy.json");
const market = load("card-market.json");
const pick = load("card-candidate-scored.json");
const digest = load("card-digest.json");
const dossier = { ref: "d055", kind: DOSSIER_CARD_KIND, title: "建 K 档案:12V电钻电池组", conclusion: "读完了,3 处标红。", status: "pending", confidence: "medium", created_at: null, evidence: { dossier_id: 7, offer_id: "643348607768", flagged_count: 3 } };
const blocked = { ref: "b10c", kind: BLOCKED_CARD_KIND, title: "PTB-001 卡在「出图」", conclusion: "出图试了 2 次都没成,我先停在这儿。批 = 让我再试一次;驳 = 这个品先不做。", status: "pending", confidence: "high", created_at: null, evidence: { dossier_id: 7, k_product_id: "x", sku: "PTB-001", step: "render" } };

test("七个家族:每种 kind 都落到一个家族,要你批的排前、只看的排后;没见过的 kind 当提醒", () => {
  assert.equal(familyOf("candidate"), "pick");
  assert.equal(familyOf(DOSSIER_CARD_KIND), "dossier");
  assert.equal(familyOf("k_price"), "price");
  assert.equal(familyOf("k_copy"), "copy");
  assert.equal(familyOf("k_review"), "review");
  assert.equal(familyOf("market"), "market");
  for (const kind of ["ops_alert", "product_blocker", "goal", "other", BLOCKED_CARD_KIND, "something_new"]) assert.equal(familyOf(kind), "alert", kind);
  assert.equal(familyOf("ops_digest"), "digest"); // 运营看板周报(10-30):只看不用批,排最后
  assert.deepEqual(FAMILY_ORDER, ["dossier", "price", "copy", "review", "pick", "alert", "market", "digest"]);
  assert.equal(FAMILIES.digest.needsDecision, false);
  assert.match(familyMeta("ops_digest").ask, /不用批/);
  assert.ok(FAMILY_ORDER.every((f) => FAMILIES[f].label && FAMILIES[f].icon && FAMILIES[f].ask));
  assert.equal(FAMILIES.market.needsDecision, false);
  assert.match(familyMeta("market").ask, /不用批/);
});

test("分组:空组不画,组按家族顺序,组内保持传入顺序", () => {
  const groups = groupCards([market, pick, price, blocked, review, dossier, copy, { ...pick, ref: "c0df" }]);
  assert.deepEqual(
    groups.map((g) => [g.meta.family, g.cards.map((c) => c.ref)]),
    [
      ["dossier", ["d055"]],
      ["price", [price.ref]],
      ["copy", [copy.ref]],
      ["review", [review.ref]],
      ["pick", [pick.ref, "c0df"]],
      ["alert", ["b10c"]],
      ["market", [market.ref]],
    ],
  );
  assert.deepEqual(groupCards([]), []);
});

test("每种卡一行基本信息:说的是哪件货、几个关键数,不是一段话", () => {
  const p = summaryOf(pick);
  assert.equal(p.headline, pick.evidence.title_zh); // 旧卡没有她翻的英文名 → 中文标题;F 的画像名(Survival Compass)是搜货目标词,不上卡
  assert.match(p.facts[0], /^进价 ¥4\.4 ≈ \$0\.61,起订 1$/);
  assert.match(p.facts.join(" "), /美国同类中位 \$10\.99/);
  assert.match(p.facts.join(" "), /评分 \d+\/100/);
  // 10-28 起:英文名按实物、同类价按件折算
  const stakes = { ...pick, evidence: { ...pick.evidence, name_en: "tent stakes", competitors: { ...pick.evidence.competitors, median: 35.97, unit: { n: 35, p25: 1.2, median: 1.62, p75: 4.81, pack_mode: 12, multi_share: 0.5 } } } };
  const s = summaryOf(stakes);
  assert.equal(s.headline, "tent stakes");
  assert.match(s.facts.join(" "), /美国同类按件 \$1\.62\/件,主流 12 件装/);
  assert.doesNotMatch(s.facts.join(" "), /中位 \$35\.97/);

  const d = summaryOf(dossier);
  assert.equal(d.headline, "12V电钻电池组");
  assert.deepEqual(d.facts, ["标红 3 处要你定", "1688 货号 643348607768"]);

  const pr = summaryOf(price);
  assert.equal(pr.headline, price.evidence.sku);
  assert.match(pr.facts[0], /个规格$/);
  assert.match(pr.facts[1], /^建议 \$/);
  assert.match(pr.facts.join(" "), /毛利 \d+%–\d+%/);

  const c = summaryOf(copy);
  assert.match(c.headline, /^PSPE-001 · Portable Camping Shower/);
  assert.deepEqual(c.facts, ["她改了 2 处", "1 处要你定", "作图指令暂停"]);

  const r = summaryOf(review);
  assert.match(r.facts[0], /^\d+ 张图$/);

  const m = summaryOf(market);
  assert.equal(m.headline, "NAV-001");
  assert.deepEqual(m.facts, ["读了 2 家", "3 条要点", "7 个关键词", "缺 2 项事实"]);

  const b = summaryOf(blocked);
  assert.equal(b.headline, "PTB-001 · 卡在 render");
  assert.equal(b.facts[0], "出图试了 2 次都没成,我先停在这儿");
});

test("把握、等了多久、缩略图地址(走已放行的代理路径)", () => {
  assert.equal(confidenceLabel("high"), "把握高");
  assert.equal(confidenceLabel("low"), "把握低");
  assert.equal(confidenceLabel("medium"), "把握中");
  const now = Date.parse("2026-10-27T12:00:00Z");
  assert.equal(waitedText("2026-10-27T11:59:30Z", now), "刚发的");
  assert.equal(waitedText("2026-10-27T11:20:00Z", now), "等了 40 分钟");
  assert.equal(waitedText("2026-10-27T03:00:00Z", now), "等了 9 小时");
  assert.equal(waitedText("2026-10-24T12:00:00Z", now), "等了 3 天");
  assert.equal(waitedText(null, now), "");
  assert.equal(cardImageUrl("c0de"), "/api/backend/suqinghe/cards/c0de/image");
  assert.equal(isAllowedBackendProxyPath("GET", ["suqinghe", "cards", "c0de", "image"]), true);
});

test("收件筐按家族分组、纸片有戳记和缩略图、卷宗有「← 回收件筐」;旧入口 CardItem 还在给场景面板用", () => {
  const parts = read("frontend/src/components/suqinghe/OfficeParts.tsx");
  assert.match(parts, /export function Inbox\(/);
  assert.match(parts, /groupCards\(office\.pending_cards\)/);
  assert.match(parts, /export function CardSheet\(/);
  assert.match(parts, /className=\{styles\.stamp\} data-family=\{meta\.family\}/);
  assert.match(parts, /src=\{cardImageUrl\(card\.ref\)\}/);
  assert.match(parts, /onError=\{\(\) => setFailed\(true\)\}/);
  assert.match(parts, /export function CardDossier\(/);
  assert.match(parts, /← 回收件筐/);
  assert.match(parts, /export function CardItem\(/);
  const window = read("frontend/src/components/suqinghe/OfficeWindow.tsx");
  assert.match(window, /<Inbox busy=\{busy\} canCommand=\{canCommand\} office=\{office\} run=\{run\} \/>/);
  const css = read("frontend/src/components/suqinghe/Office.module.css");
  for (const family of FAMILY_ORDER) assert.match(css, new RegExp(`\\.sheet\\[data-family="${family}"\\]`), family);
  assert.match(css, /inbox_bg\.webp/);
});


test("看板卡(10-30):一行基本信息写周、异常条数、几节;列表里的看板路径进了代理白名单", () => {
  const summary = summaryOf(digest);
  assert.equal(summary.headline, "2026-W44 运营看板");
  assert.ok(summary.facts.includes("2026-10-26 ~ 2026-11-01"));
  assert.ok(summary.facts.some((f) => /条要看的异常/.test(f)) && summary.facts.some((f) => /节$/.test(f)));
  assert.equal(isAllowedBackendProxyPath("GET", ["suqinghe", "digests"]), true);
  assert.equal(isAllowedBackendProxyPath("GET", ["suqinghe", "digests", "week", "2026-W44"]), true);
  assert.equal(isAllowedBackendProxyPath("GET", ["suqinghe", "digests", "day", "2026-10-29"]), true);
  assert.equal(isAllowedBackendProxyPath("GET", ["suqinghe", "digests", "month", "2026-10"]), false);
  assert.equal(isAllowedBackendProxyPath("GET", ["suqinghe", "digests", "week", "../x"]), false);
  assert.equal(isAllowedBackendProxyPath("POST", ["suqinghe", "digests"]), false);
  const parts = read("frontend/src/components/suqinghe/OfficeParts.tsx");
  assert.match(parts, /DIGEST_CARD_KIND \? <DigestCardBody/);
  assert.match(parts, /export function DigestPanel/);
  assert.match(read("frontend/src/components/suqinghe/OfficeWindow.tsx"), /<h3>看板<\/h3>\s*<DigestPanel digest=\{office\.digest\}/);
});
