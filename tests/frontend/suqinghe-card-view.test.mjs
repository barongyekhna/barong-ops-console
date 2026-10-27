// 苏青禾的价格卡、审核卡(10-26):卡片 evidence → 界面那一层。
//
// 夹具是用后端真代码拼出来的(pricing.cost_lines / apply_plan、pipeline._copy_summary,照 _step_price_card
// 的写法),不是手写的 JSON——档案柜那次两边测试都绿、中间这层对不上,这里就喂后端真产出。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { isAllowedBackendProxyPath } from "../../frontend/src/app/api/backend/[...path]/route.ts";
import { CANDIDATE_CARD_KIND, PRICE_CARD_KIND, REVIEW_CARD_KIND, candidateCardView, candidateImageUrl, kMediaThumbnailUrl, pct, priceCardView, reviewCardView, usd } from "../../frontend/src/components/suqinghe/card-view.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const load = (name) => JSON.parse(readFileSync(path.join(here, "fixtures", "suqinghe", name), "utf8"));
const price = load("card-price-643348607768.json");
const review = load("card-review-643348607768.json");
const read = (rel) => readFileSync(path.join(here, "..", "..", rel), "utf8");

test("价格卡:一行一个规格,混进来的充电器标「不卖」,低于保底的价已经抬上去", () => {
  assert.equal(price.kind, PRICE_CARD_KIND);
  const view = priceCardView(price.evidence);
  assert.ok(view);
  assert.equal(view.rows.length, 5);
  const byName = Object.fromEntries(view.rows.map((row) => [row.name, row]));
  assert.equal(byName["12V Charger"].include, false);
  assert.match(byName["12V Charger"].note, /充电器/);
  assert.equal(byName["2000mAh"].priceUsd, 19.99);
  assert.equal(byName["2000mAh"].costCny, 39);
  assert.ok(byName["2000mAh"].landedUsd > 10 && byName["2000mAh"].landedUsd < 11);
  // 货和运费分开摆,老板一眼看出钱花在哪
  assert.equal(byName["2000mAh"].goodsUsd, 5.42);
  assert.equal(byName["2000mAh"].shipUsd, 4.9);
  assert.equal(byName["2000mAh"].kg, 0.17);
  assert.match(view.shippingRule, /计费重 × ¥90\/公斤 \+ ¥20\/件/);
  assert.match(view.shippingRule, /不是真实报价/);
  assert.match(byName["1300mAh"].note, /抬到保底价/);
  assert.equal(view.shippingClass, "cn-direct-standard");
  assert.equal(view.battery, true);
  assert.match(view.competitors, /中位 \$39\.95/);
  assert.deepEqual(view.questions, ["这款通用电池配哪些牌子的电钻?"]);
  assert.equal(usd(19.99), "$19.99");
  assert.equal(pct(0.384), "38%");
});

test("审核卡:英文标题和卖点、每张图的缩略图走 K 的媒体接口、审查发现和合规都摆出来", () => {
  assert.equal(review.kind, REVIEW_CARD_KIND);
  const view = reviewCardView(review.evidence);
  assert.ok(view);
  assert.equal(view.h1, "12V Lithium Drill Battery Pack");
  assert.deepEqual(view.bullets, ["Brand-new 18650 cells", "Up to 500 cycles"]);
  assert.equal(view.images.length, 2);
  assert.equal(view.images[0].thumb, kMediaThumbnailUrl("0dfd2588-8e83-49eb-b752-a9525bbd2090"));
  assert.equal(view.auditClean, false);
  assert.match(view.auditFindings[0], /第 2 张图/);
  assert.deepEqual(view.concerns, ["锂电池要按带电渠道运输"]);
  assert.deepEqual(view.held, ["通过 UL 1642 认证"]);
  assert.deepEqual(view.prices, ["2000mAh $19.99"]);
});

test("缩略图地址走前端代理已经放行的 K 媒体路径;卡片正文不藏在「展开」里", () => {
  assert.equal(kMediaThumbnailUrl("a b"), "/api/backend/k/media/a%20b/thumbnail");
  for (const tail of ["thumbnail", "file"]) {
    const url = kMediaThumbnailUrl("0dfd2588-8e83-49eb-b752-a9525bbd2090").replace(/thumbnail$/, tail);
    assert.ok(isAllowedBackendProxyPath("GET", url.replace("/api/backend/", "").split("/")), url);
  }
  const parts = read("frontend/src/components/suqinghe/OfficeParts.tsx");
  assert.match(parts, /card\.kind === PRICE_CARD_KIND \? <PriceCardBody evidence=\{card\.evidence\} \/> : null/);
  assert.match(parts, /card\.kind === REVIEW_CARD_KIND \? <ReviewCardBody evidence=\{card\.evidence\} \/> : null/);
  assert.match(parts, /<dd className=\{styles\.preLine\}>\{card\.why\}<\/dd>/);
});

test("坏的 evidence 不画,不炸", () => {
  assert.equal(priceCardView(null), null);
  assert.equal(priceCardView({ variants: [] }), null);
});

test("选品卡:图走后端代理、进价折美元、美国同类价、风险一条一条,1688 链接只认 detail 页", () => {
  const candidate = JSON.parse(read("tests/frontend/fixtures/suqinghe/card-candidate.json"));
  assert.equal(candidate.kind, CANDIDATE_CARD_KIND);
  const view = candidateCardView(candidate.evidence);
  assert.ok(view);
  assert.match(view.titleZh, /套锅/);
  assert.equal(view.category, "Camping & Hiking > Camping Cookware & Dinnerware");
  assert.equal(view.priceCny, 23);
  assert.equal(view.goodsUsd, 3.19);
  assert.equal(view.moq, 1);
  assert.equal(view.monthlySales, 400);
  assert.match(view.competitors, /中位 \$27\.99/);
  assert.match(view.reason, /起订 1/);
  assert.equal(view.risks.length, 2);
  assert.equal(view.sourceUrl, "https://detail.1688.com/offer/888700112233.html");
  assert.equal(view.hasImage, true);
  assert.equal(candidateImageUrl(candidate.ref), "/api/backend/suqinghe/cards/c0de/image");
  // 卡上的话由后端定,前端不再拼一遍
  assert.match(candidate.conclusion, /进价 ¥23\.0\(≈\$3\.19\)/);
  assert.match(candidate.why, /重量/);
  const noLink = candidateCardView({ ...candidate.evidence, source_url: "https://evil.example/x", image_url: "" });
  assert.equal(noLink.sourceUrl, "");
  assert.equal(noLink.hasImage, false);
  assert.equal(candidateCardView({ title_zh: "" }), null);
  assert.equal(reviewCardView("x"), null);
});
