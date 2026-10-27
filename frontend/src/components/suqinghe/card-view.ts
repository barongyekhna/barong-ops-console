/**
 * 苏青禾的价格卡、审核卡:卡片 evidence → 界面要画的东西(纯函数,node 测试直接验)。
 * evidence 的结构由后端 pipeline.py 定;这里只挑要画的字段,缺什么就不画什么,不猜。
 */

type Rec = Record<string, unknown>;

const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): string => (typeof value === "string" ? value.trim() : "");
const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const strings = (value: unknown): string[] => list(value).map(text).filter(Boolean);

export const PRICE_CARD_KIND = "k_price";
export const REVIEW_CARD_KIND = "k_review";

export function kMediaThumbnailUrl(assetId: string): string {
  return `/api/backend/k/media/${encodeURIComponent(assetId)}/thumbnail`;
}

export type PriceRow = {
  name: string;
  nameZh: string;
  include: boolean;
  costCny: number | null;
  goodsUsd: number | null;
  shipUsd: number | null;
  kg: number | null;
  landedUsd: number | null;
  priceUsd: number | null;
  profitUsd: number | null;
  margin: number | null;
  note: string;
};

export type PriceCardView = {
  rows: PriceRow[];
  questions: string[];
  summary: string;
  competitors: string;
  shippingClass: string;
  battery: boolean;
  shippingRule: string;
};

export function priceCardView(evidence: unknown): PriceCardView | null {
  if (!isRec(evidence)) return null;
  const rows: PriceRow[] = list(evidence.variants)
    .filter(isRec)
    .map((line) => {
      const goods = num(line.goods);
      const ship = num(line.ship);
      return {
        name: text(line.label_en) || text(line.name_en) || text(line.name_zh),
        nameZh: text(line.name_zh),
        include: line.include !== false,
        costCny: num(line.cost_cny),
        goodsUsd: goods,
        shipUsd: ship,
        kg: num(line.kg),
        landedUsd: goods !== null && ship !== null ? Math.round((goods + ship) * 100) / 100 : null,
        priceUsd: num(line.price),
        profitUsd: num(line.profit),
        margin: num(line.margin),
        note: [text(line.note), text(line.weight_note)].filter(Boolean).join(";"),
      };
    });
  if (rows.length === 0) return null;
  const comp = isRec(evidence.competitors) ? evidence.competitors : {};
  const n = num(comp.n) ?? 0;
  const competitors =
    n > 0
      ? `谷歌购物「${text(comp.query)}」${n} 个:中位 $${num(comp.median)},一半在 $${num(comp.p25)}–$${num(comp.p75)}`
      : `竞品价没拿到${text(comp.error) ? `(${text(comp.error)})` : ""}`;
  const shipping = isRec(evidence.shipping) ? evidence.shipping : {};
  const a = isRec(evidence.assumptions) ? evidence.assumptions : {};
  const perKg = num(a.ship_cny_per_kg);
  const perPiece = num(a.ship_cny_per_piece);
  const rate = num(a.usd_cny);
  const shippingRule =
    perKg !== null && perPiece !== null
      ? `运费 = 计费重 × ¥${perKg}/公斤 + ¥${perPiece}/件${rate !== null ? `,按 ${rate} 换美元` : ""}(估的带电专线价,不是真实报价)`
      : "";
  return {
    rows,
    questions: strings(evidence.questions),
    summary: text(evidence.summary),
    competitors,
    shippingClass: text(shipping.class),
    battery: shipping.contains_battery === true,
    shippingRule,
  };
}

export type ReviewImage = { assetId: string; position: number; role: string; thumb: string };

export type ReviewCardView = {
  h1: string;
  headline: string;
  bullets: string[];
  faq: number;
  images: ReviewImage[];
  auditClean: boolean;
  auditFindings: string[];
  concerns: string[];
  held: string[];
  hype: string[];
  flagged: string[];
  prices: string[];
};

export function reviewCardView(evidence: unknown): ReviewCardView | null {
  if (!isRec(evidence)) return null;
  const copy = isRec(evidence.copy) ? evidence.copy : {};
  const audit = isRec(evidence.audit) ? evidence.audit : {};
  const images: ReviewImage[] = list(evidence.images)
    .filter(isRec)
    .map((image) => ({
      assetId: text(image.asset_id),
      position: num(image.position) ?? 0,
      role: text(image.role),
      thumb: text(image.asset_id) ? kMediaThumbnailUrl(text(image.asset_id)) : "",
    }))
    .filter((image) => image.assetId);
  const findings = list(audit.violations)
    .filter(isRec)
    .map((v) => (v.kind === "image" ? `第 ${num(v.position) ?? "?"} 张图:${text(v.finding)}` : `文字:${text(v.finding)}`));
  return {
    h1: text(copy.h1) || text(copy.title),
    headline: text(copy.headline),
    bullets: strings(copy.bullets),
    faq: num(copy.faq) ?? 0,
    images,
    auditClean: audit.clean === true && findings.length === 0,
    auditFindings: [...findings, ...strings(audit.errors).map((e) => `审查出错:${e}`)],
    concerns: strings(evidence.concerns),
    held: strings(evidence.held_certifications),
    hype: strings(evidence.hype),
    flagged: strings(evidence.flagged),
    prices: list(evidence.prices)
      .filter(isRec)
      .map((p) => `${text(p.label)} $${num(p.price) ?? "?"}`),
  };
}

export const CANDIDATE_CARD_KIND = "candidate";

/** 选品卡上的候选图:后端经 F 的图片缓存回源阿里 CDN,前端不直连 1688。 */
export function candidateImageUrl(ref: string): string {
  return `/api/backend/suqinghe/cards/${encodeURIComponent(ref)}/image`;
}

/** 评分卡(10-27):六个维度各自的分、满分、依据、出处;没拿到数据的维度标出来。 */
export type ScoreDim = { key: string; label: string; pts: number; max: number; why: string; source: string; missing: boolean };
export type ScoreView = { total: number; max: number; dims: ScoreDim[]; missing: string[]; weightClass: string; amazon: string; keepa: string };

export type CandidateCardView = {
  titleZh: string;
  category: string;
  priceCny: number | null;
  goodsUsd: number | null;
  moq: number | null;
  monthlySales: number | null;
  competitors: string;
  reason: string;
  risks: string[];
  sourceUrl: string;
  hasImage: boolean;
  score: ScoreView | null;
};

const WEIGHT_LABEL: Record<string, string> = { light: "轻小件", medium: "中等", heavy: "大件重件" };

export function scoreView(evidence: Rec): ScoreView | null {
  const score = isRec(evidence.scorecard) ? evidence.scorecard : null; // evidence.score 是 F 池的分,评分卡在 scorecard
  if (!score) return null;
  const dims: ScoreDim[] = list(score.dims)
    .filter(isRec)
    .map((d) => ({
      key: text(d.key),
      label: text(d.label),
      pts: num(d.pts) ?? 0,
      max: num(d.max) ?? 0,
      why: text(d.why),
      source: text(d.source),
      missing: d.missing === true,
    }))
    .filter((d) => d.label);
  if (dims.length === 0) return null;
  const amazon = isRec(evidence.amazon) ? evidence.amazon : {};
  const wall = num(amazon.review_wall_max);
  const share = num(amazon.single_brand_share);
  const amazonText = text(amazon.error)
    ? `亚马逊没查到(${text(amazon.error)})`
    : amazon.valid === false
      ? "亚马逊结果和关键词对不上,没用"
      : `亚马逊首页:前三名最高评论 ${wall ?? "?"} 条${share !== null ? `,单一品牌占 ${Math.round(share * 100)}%` : ""}${text(amazon.dominant_brand) ? `(${text(amazon.dominant_brand)})` : ""}`;
  const keepa = list(evidence.keepa).filter(isRec);
  const sales = keepa.map((k) => num(k.monthly_sales)).filter((v): v is number => v !== null);
  const keepaText = sales.length > 0 ? `前 ${sales.length} 名月销 ${sales.map((v) => Math.round(v)).join(" / ")} 件` : "月销没拿到";
  return {
    total: num(score.total) ?? 0,
    max: num(score.max) ?? 100,
    dims,
    missing: strings(score.missing),
    weightClass: WEIGHT_LABEL[text(evidence.weight_class)] ?? "",
    amazon: amazonText,
    keepa: keepaText,
  };
}

const DETAIL_1688 = /^https:\/\/detail\.1688\.com\/offer\/\d+\.html/;

export function candidateCardView(evidence: unknown): CandidateCardView | null {
  if (!isRec(evidence)) return null;
  const titleZh = text(evidence.title_zh);
  if (!titleZh) return null;
  const comp = isRec(evidence.competitors) ? evidence.competitors : {};
  const n = num(comp.n) ?? 0;
  const competitors =
    n > 0
      ? `美国同类「${text(comp.query)}」${n} 个:中位 $${num(comp.median)},一半在 $${num(comp.p25)}–$${num(comp.p75)}`
      : `美国同类价没拿到${text(comp.error) ? `(${text(comp.error)})` : ""}`;
  const path = text(evidence.category_path)
    .split(">")
    .map((part) => part.trim())
    .filter(Boolean);
  const sourceUrl = text(evidence.source_url);
  return {
    titleZh,
    category: path.slice(-2).join(" > "),
    priceCny: num(evidence.price_cny),
    goodsUsd: num(evidence.goods_usd),
    moq: num(evidence.moq),
    monthlySales: num(evidence.monthly_sales),
    competitors,
    reason: text(evidence.reason),
    risks: strings(evidence.risks),
    sourceUrl: DETAIL_1688.test(sourceUrl) ? sourceUrl : "",
    hasImage: Boolean(text(evidence.image_url)),
    score: scoreView(evidence),
  };
}

export const MARKET_CARD_KIND = "market";

export type MarketPage = { domain: string; title: string; price: number | null; bullets: number; faq: number; images: number | null; highlight: string; ok: boolean; error: string };
export type MarketPriority = { what: string; why: string };

/** 竞品拆解卡(10-27):读了哪几家、买家最在乎什么、我们有无、四簇关键词、缺的事实。给老板看,不用批。 */
export type MarketCardView = {
  query: string;
  pages: MarketPage[];
  priceBand: string;
  priorities: MarketPriority[];
  has: string[];
  missing: string[];
  gaps: string[];
  keywords: { label: string; items: string[] }[];
  competitors: string[];
  note: string;
};

const CLUSTER_LABEL: [string, string][] = [
  ["category", "品类词"],
  ["attribute", "属性词"],
  ["scene", "场景词"],
  ["question", "问题句"],
];

export function marketCardView(evidence: unknown): MarketCardView | null {
  if (!isRec(evidence)) return null;
  const pages: MarketPage[] = list(evidence.pages)
    .filter(isRec)
    .map((p) => ({
      domain: text(p.domain),
      title: text(p.title),
      price: num(p.price),
      bullets: num(p.bullets) ?? 0,
      faq: num(p.faq) ?? 0,
      images: num(p.image_count),
      highlight: text(p.highlight),
      ok: p.ok === true,
      error: text(p.error),
    }))
    .filter((p) => p.domain);
  const priorities: MarketPriority[] = list(evidence.priorities)
    .filter(isRec)
    .map((p) => ({ what: text(p.what), why: text(p.why) }))
    .filter((p) => p.what);
  if (pages.length === 0 && priorities.length === 0) return null;
  const prices = pages.map((p) => p.price).filter((v): v is number => v !== null);
  const ours = isRec(evidence.ours) ? evidence.ours : {};
  const kw = isRec(evidence.keywords) ? evidence.keywords : {};
  const comp = isRec(evidence.competitors) ? evidence.competitors : {};
  return {
    query: text(evidence.query),
    pages,
    priceBand: prices.length > 0 ? `$${Math.min(...prices).toFixed(0)}–$${Math.max(...prices).toFixed(0)}` : "",
    priorities,
    has: strings(ours.has),
    missing: strings(ours.missing),
    gaps: strings(evidence.gaps),
    keywords: CLUSTER_LABEL.map(([key, label]) => ({ label, items: strings(kw[key]) })).filter((c) => c.items.length > 0),
    competitors: [...strings(comp.brands), ...strings(comp.domains)],
    note: text(evidence.note),
  };
}

export const COPY_CARD_KIND = "k_copy";

export type CopySection = { heading: string; body: string };
export type CopyFaq = { question: string; answer: string };

/** 文案卡(10-27):老板看全文——她读过改过的那版,加上她的中文摘要、改了什么、拿不准什么。 */
export type CopyCardView = {
  h1: string;
  seoTitle: string;
  metaDescription: string;
  urlSlug: string;
  headline: string;
  subheadline: string;
  shortDescription: string;
  bullets: string[];
  sections: CopySection[];
  conversion: string;
  faq: CopyFaq[];
  summaryZh: string;
  notes: string[];
  unsure: string[];
  changed: string[];
  adjusted: string[];
  historyUnclear: string;
  held: string[];
  hype: string[];
  flagged: string[];
  missingInputs: string[];
  briefPaused: boolean;
};

export function copyCardView(evidence: unknown): CopyCardView | null {
  if (!isRec(evidence)) return null;
  const copy = isRec(evidence.copy) ? evidence.copy : {};
  const seo = isRec(copy.seo) ? copy.seo : {};
  const check = isRec(evidence.check) ? evidence.check : {};
  const sections: CopySection[] = list(copy.sections)
    .filter(isRec)
    .map((s) => ({ heading: text(s.heading), body: text(s.body) }))
    .filter((s) => s.heading || s.body);
  const faq: CopyFaq[] = list(copy.faq)
    .filter(isRec)
    .map((f) => ({ question: text(f.question), answer: text(f.answer) }))
    .filter((f) => f.question);
  const h1 = text(seo.h1);
  const headline = text(copy.headline);
  if (!h1 && !headline && sections.length === 0) return null;
  return {
    h1,
    seoTitle: text(seo.title),
    metaDescription: text(seo.meta_description),
    urlSlug: text(seo.url_slug),
    headline,
    subheadline: text(copy.subheadline),
    shortDescription: text(copy.short_description),
    bullets: strings(copy.bullets),
    sections,
    conversion: text(copy.conversion_support_block),
    faq,
    summaryZh: text(check.summary_zh),
    notes: strings(check.notes),
    unsure: strings(check.unsure),
    changed: strings(check.changed),
    adjusted: list(check.adjusted)
      .filter(isRec)
      .map((a) => `${text(a.field)}:想改成「${text(a.wanted)}」,K 核证据后留的是「${text(a.got)}」`),
    historyUnclear: text(evidence.history_unclear),
    held: strings(evidence.held_certifications),
    hype: strings(evidence.hype),
    flagged: strings(evidence.flagged),
    missingInputs: strings(copy.missing_inputs),
    briefPaused: evidence.brief_paused === true,
  };
}

export function usd(value: number | null): string {
  return value === null ? "—" : `$${value.toFixed(2)}`;
}

export function pct(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}
