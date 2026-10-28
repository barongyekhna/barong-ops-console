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
import {
  CANDIDATE_CARD_KIND,
  COPY_CARD_KIND,
  MARKET_CARD_KIND,
  PRICE_CARD_KIND,
  REVIEW_CARD_KIND,
  candidateCardView,
  candidateImageUrl,
  copyCardView,
  kMediaThumbnailUrl,
  marketCardView,
  pct,
  priceCardView,
  reviewCardView,
  usd,
} from "../../frontend/src/components/suqinghe/card-view.ts";

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
  // 10-28:她翻的英文名 + 同类价按件折算(单根和 12 支装混在一起时,卡上说明 1688 进价是单件价)
  assert.equal(view.nameEn, "");
  assert.equal(view.unit, null);
  const packs = candidateCardView({ ...candidate.evidence, name_en: "tent stakes", competitors: { ...candidate.evidence.competitors, unit: { n: 10, p25: 1.2, median: 1.62, p75: 4.81, pack_mode: 12, multi_share: 0.5 } } });
  assert.equal(packs.nameEn, "tent stakes");
  assert.deepEqual(packs.unit, { median: 1.62, p25: 1.2, packMode: 12, multiShare: 0.5 });
  assert.match(packs.competitors, /按件折算中位 \$1\.62\/件,主流 12 件装\(50% 是多件装\)——1688 的进价是单件价/);
  const singles = candidateCardView({ ...candidate.evidence, competitors: { ...candidate.evidence.competitors, unit: { n: 10, p25: 20, median: 27.99, p75: 30, pack_mode: 1, multi_share: 0 } } });
  assert.equal(singles.unit, null);
  assert.doesNotMatch(singles.competitors, /按件折算/);
});

test("文案卡:全文一字不少(标题/钩子/短描述/卖点/段落/收尾/FAQ/SEO),她的中文摘要、改了什么、拿不准什么分开摆;作图指令暂停有提示", () => {
  const copy = load("card-copy.json");
  assert.equal(copy.kind, COPY_CARD_KIND);
  assert.equal(COPY_CARD_KIND, "k_copy");
  const view = copyCardView(copy.evidence);
  assert.ok(view);
  assert.equal(view.h1, "Portable Camping Shower – Rechargeable off-grid rinses");
  assert.match(view.seoTitle, /\| Barong Yekhna$/);
  assert.equal(view.urlSlug, "portable-camping-shower-kit");
  assert.equal(view.headline, "Rinse clean wherever the trail takes you");
  assert.match(view.shortDescription, /2\.11 GPM/);
  assert.equal(view.bullets.length, 14);
  assert.equal(view.sections.length, 5);
  assert.ok(view.sections.every((s) => s.heading && s.body));
  assert.match(view.conversion, /van life/);
  assert.equal(view.faq.length, 6);
  assert.ok(view.faq[0].question.endsWith("?") && view.faq[0].answer.length > 20);
  // 她的说明和英文正文分开:中文摘要、改了什么、K 收回去的、拿不准的
  assert.match(view.summaryZh, /便携露营淋浴/);
  assert.deepEqual(view.notes, ["钩子从产品名改成买家结果(Rinse off anywhere)", "FAQ 第 1 条答案收短到两句"]);
  assert.equal(view.unsure.length, 1);
  assert.match(view.adjusted[0], /^seo\.h1:想改成「Portable Camping Shower – Heats Water Fast」/);
  assert.deepEqual(view.held, ["IPX7 防水(卖家自填)"]);
  assert.deepEqual(view.hype, ["Best seller in 2026"]);
  assert.equal(view.briefPaused, true);
  // 内部字段不进卡:证据指纹、规格表 HTML
  assert.equal(JSON.stringify(copy.evidence.copy).includes("specifications_html_table"), false);
  // 坏的 evidence 不画,不炸
  assert.equal(copyCardView(null), null);
  assert.equal(copyCardView({ copy: { seo: {} } }), null);
});

test("文案卡的正文由 OfficeParts 按 kind 画;K 的改稿接口进了代理白名单(PUT,别的形状不放)", () => {
  const parts = read("frontend/src/components/suqinghe/OfficeParts.tsx");
  assert.match(parts, /card\.kind === COPY_CARD_KIND \? <CopyCardBody/);
  assert.match(parts, /lang="en"/);
  const uuid = "01234567-89ab-4def-8123-456789abcdef";
  assert.equal(isAllowedBackendProxyPath("PUT", ["k", "products", uuid, "marketing-copy"]), true);
  assert.equal(isAllowedBackendProxyPath("POST", ["k", "products", uuid, "marketing-copy"]), false);
  assert.equal(isAllowedBackendProxyPath("GET", ["k", "products", uuid, "marketing-copy"]), false);
  assert.equal(isAllowedBackendProxyPath("PUT", ["k", "products", "not-a-uuid", "marketing-copy"]), false);
  assert.equal(isAllowedBackendProxyPath("PUT", ["k", "products", uuid, "marketing-copy", "x"]), false);
});

test("选品卡带评分:五个维度各有分、满分、依据,没拿到的标出来,亚马逊和 Keepa 的数据写成人话;老卡没评分照样画", () => {
  const scored = load("card-candidate-scored.json");
  assert.equal(scored.kind, CANDIDATE_CARD_KIND);
  const view = candidateCardView(scored.evidence);
  assert.ok(view && view.score);
  assert.deepEqual(
    view.score.dims.map((d) => d.label),
    ["账算得过", "有人买", "竞争", "和工厂的关系", "合规物流"],
  );
  assert.equal(view.score.max, 100);
  assert.equal(
    view.score.total,
    view.score.dims.reduce((sum, d) => sum + d.pts, 0),
  );
  assert.ok(view.score.dims.every((d) => d.max > 0 && d.why && d.source));
  assert.equal(view.score.weightClass, "轻小件");
  assert.match(view.score.amazon, /前三名最高评论 1800 条/);
  assert.match(view.score.keepa, /月销 900 \/ 400 件/);
  assert.match(scored.why, /按估计重量/);
  // 10-27 之前发的选品卡没有 score:视图里是 null,不炸
  const old = load("card-candidate.json");
  assert.equal(candidateCardView(old.evidence).score, null);
});

test("竞品拆解卡:读了哪几家(没读到的标原因)、买家最在乎什么、我们有无、缺的事实、四簇关键词、竞品、价格带;卡上写明不用批", () => {
  const market = load("card-market.json");
  assert.equal(market.kind, MARKET_CARD_KIND);
  assert.equal(MARKET_CARD_KIND, "market");
  assert.match(market.conclusion, /不用批/);
  const view = marketCardView(market.evidence);
  assert.ok(view);
  assert.equal(view.query, "hiking map compass");
  assert.equal(view.pages.length, 3);
  assert.equal(view.pages[2].ok, false);
  assert.match(view.pages[2].error, /被拦/);
  assert.equal(view.priceBand, "$12–$15");
  assert.equal(view.priorities.length, 3);
  assert.match(view.priorities[0].what, /充液/);
  assert.deepEqual(view.missing, ["是否充液", "磁偏角调节"]);
  assert.equal(view.gaps.length, 2);
  assert.deepEqual(
    view.keywords.map((c) => c.label),
    ["品类词", "属性词", "场景词", "问题句"],
  );
  assert.deepEqual(view.competitors, ["Suunto", "Silva", "shop-a.com", "shop-b.com"]);
  assert.equal(marketCardView({ pages: [], priorities: [] }), null);
  const parts = read("frontend/src/components/suqinghe/OfficeParts.tsx");
  assert.match(parts, /card\.kind === MARKET_CARD_KIND \? <MarketCardBody/);
  assert.match(parts, /view\.score \? \(/);
});
