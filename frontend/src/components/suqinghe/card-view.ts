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
};

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
  };
}

export function usd(value: number | null): string {
  return value === null ? "—" : `$${value.toFixed(2)}`;
}

export function pct(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}
