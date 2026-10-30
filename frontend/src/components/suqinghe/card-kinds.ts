/**
 * 苏青禾的卡分七个「家族」(10-27 卡片重做):每张卡是什么、要老板做什么、一行基本信息。
 * 纯函数,node 测试直接验;evidence 的字段只挑要画的,缺什么就不画。
 */

import { CANDIDATE_CARD_KIND, COPY_CARD_KIND, DIGEST_CARD_KIND, MARKET_CARD_KIND, PRICE_CARD_KIND, REVIEW_CARD_KIND, candidateCardView, copyCardView, digestCardView, marketCardView, priceCardView, reviewCardView } from "./card-view";
import type { OfficeCard } from "./office-api";

export const DOSSIER_CARD_KIND = "create_k_dossier";
export const BLOCKED_CARD_KIND = "k_blocked";

export type Family = "dossier" | "price" | "copy" | "review" | "pick" | "alert" | "market" | "digest";

export type FamilyMeta = {
  family: Family;
  label: string;
  icon: string;
  /** 批了她会做什么;只看的卡写「不用批」 */
  ask: string;
  /** 要老板批的排前,只看的排后 */
  order: number;
  needsDecision: boolean;
};

export const FAMILIES: Record<Family, FamilyMeta> = {
  dossier: { family: "dossier", label: "建档", icon: "📁", ask: "批了她把档案建进 K", order: 0, needsDecision: true },
  price: { family: "price", label: "定价", icon: "💲", ask: "批了她照这个价改变体、选运费模板", order: 1, needsDecision: true },
  copy: { family: "copy", label: "文案", icon: "✍️", ask: "批了锁定这版文案", order: 2, needsDecision: true },
  review: { family: "review", label: "审核", icon: "🖼️", ask: "批了她保存图片、推上独立站草稿", order: 3, needsDecision: true },
  pick: { family: "pick", label: "选品", icon: "🧭", ask: "批了她开 1688 页建档", order: 4, needsDecision: true },
  alert: { family: "alert", label: "提醒", icon: "🔔", ask: "看情况:批 = 让她再试 / 照办,驳 = 先不做", order: 5, needsDecision: true },
  market: { family: "market", label: "拆解", icon: "🔍", ask: "给你看的,不用批;驳了她撤掉这份情报重跑关键词", order: 6, needsDecision: false },
  digest: { family: "digest", label: "看板", icon: "📊", ask: "本周运营看板,给你看的,不用批;看过点「知道了」", order: 7, needsDecision: false },
};

export const FAMILY_ORDER: Family[] = ["dossier", "price", "copy", "review", "pick", "alert", "market", "digest"];

export function familyOf(kind: string): Family {
  switch (kind) {
    case DOSSIER_CARD_KIND:
      return "dossier";
    case PRICE_CARD_KIND:
      return "price";
    case COPY_CARD_KIND:
      return "copy";
    case REVIEW_CARD_KIND:
      return "review";
    case CANDIDATE_CARD_KIND:
      return "pick";
    case MARKET_CARD_KIND:
      return "market";
    case DIGEST_CARD_KIND:
      return "digest";
    default:
      return "alert";
  }
}

export function familyMeta(kind: string): FamilyMeta {
  return FAMILIES[familyOf(kind)];
}

export type CardGroup = { meta: FamilyMeta; cards: OfficeCard[] };

/** 按家族分组、空组不要、组按「要你批的在前」排;组内保持传入顺序(后端已按新到旧)。 */
export function groupCards(cards: OfficeCard[]): CardGroup[] {
  const buckets = new Map<Family, OfficeCard[]>();
  for (const card of cards) {
    const family = familyOf(card.kind);
    const list = buckets.get(family) ?? [];
    list.push(card);
    buckets.set(family, list);
  }
  return FAMILY_ORDER.filter((family) => (buckets.get(family) ?? []).length > 0).map((family) => ({ meta: FAMILIES[family], cards: buckets.get(family) ?? [] }));
}

export function cardImageUrl(ref: string): string {
  return `/api/backend/suqinghe/cards/${encodeURIComponent(ref)}/image`;
}

export type CardSummary = {
  /** 这张卡关于哪件货:SKU / 品名 / 中文标题 */
  headline: string;
  /** 一两行就够的基本信息 */
  facts: string[];
};

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): string => (typeof value === "string" ? value.trim() : "");
const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const money = (value: number | null): string => (value === null ? "—" : `$${value.toFixed(2)}`);

function firstSentence(value: string): string {
  const cut = value.split(/[。；;\n]/)[0] ?? "";
  return cut.length > 60 ? `${cut.slice(0, 60)}…` : cut;
}

export function summaryOf(card: OfficeCard): CardSummary {
  const evidence = isRec(card.evidence) ? card.evidence : {};
  const sku = text(evidence.sku);
  switch (familyOf(card.kind)) {
    case "pick": {
      const view = candidateCardView(evidence);
      if (!view) return { headline: card.title.replace(/^选品[:：]/, ""), facts: [firstSentence(card.conclusion)] };
      const facts: string[] = [];
      facts.push(`进价 ${view.priceCny === null ? "—" : `¥${view.priceCny}`}${view.goodsUsd !== null ? ` ≈ ${money(view.goodsUsd)}` : ""},起订 ${view.moq ?? "—"}`);
      const comp = isRec(evidence.competitors) ? evidence.competitors : {};
      if (view.unit) facts.push(`美国同类按件 ${money(view.unit.median)}/件,主流 ${view.unit.packMode} 件装`);
      else if (num(comp.median) !== null) facts.push(`美国同类中位 ${money(num(comp.median))}`);
      if (view.score) facts.push(`评分 ${view.score.total}/${view.score.max}${view.score.missing.length > 0 ? `(没拿到 ${view.score.missing.length} 项)` : ""}`);
      // 标题用她按实物翻的英文名;F 的画像名是当初搜货的目标词(搜「帐篷外帐」搜出来的可能是天幕杆),不上卡
      return { headline: view.nameEn || view.titleZh, facts };
    }
    case "dossier": {
      const flagged = num(evidence.flagged_count);
      const facts = [flagged && flagged > 0 ? `标红 ${flagged} 处要你定` : "没有标红", text(evidence.offer_id) ? `1688 货号 ${text(evidence.offer_id)}` : ""].filter(Boolean);
      return { headline: card.title.replace(/^建 K 档案[:：]/, ""), facts };
    }
    case "price": {
      const view = priceCardView(evidence);
      if (!view) return { headline: sku || card.title, facts: [firstSentence(card.conclusion)] };
      const rows = view.rows.filter((row) => row.include && row.priceUsd !== null);
      const prices = rows.map((row) => row.priceUsd as number);
      const margins = rows.map((row) => row.margin).filter((m): m is number => m !== null);
      const facts = [
        `${rows.length} 个规格`,
        prices.length > 0 ? `建议 ${money(Math.min(...prices))}${prices.length > 1 ? `–${money(Math.max(...prices))}` : ""}` : "",
        margins.length > 0 ? `毛利 ${Math.round(Math.min(...margins) * 100)}%–${Math.round(Math.max(...margins) * 100)}%` : "",
        view.questions.length > 0 ? `${view.questions.length} 个问题要你答` : "",
      ].filter(Boolean);
      return { headline: sku || card.title, facts };
    }
    case "copy": {
      const view = copyCardView(evidence);
      const facts = view
        ? [view.changed.length > 0 ? `她改了 ${view.changed.length} 处` : "没改动", view.unsure.length > 0 ? `${view.unsure.length} 处要你定` : "", view.briefPaused ? "作图指令暂停" : ""].filter(Boolean)
        : [firstSentence(card.conclusion)];
      return { headline: sku ? `${sku}${view?.h1 ? ` · ${view.h1}` : ""}` : card.title, facts };
    }
    case "review": {
      const view = reviewCardView(evidence);
      const facts = view
        ? [`${view.images.length} 张图`, view.auditClean ? "品牌审查干净" : `审查 ${view.auditFindings.length} 处要看`, view.concerns.length > 0 ? `合规 ${view.concerns.length} 条` : ""].filter(Boolean)
        : [firstSentence(card.conclusion)];
      return { headline: sku ? `${sku}${view?.h1 ? ` · ${view.h1}` : ""}` : card.title, facts };
    }
    case "market": {
      const view = marketCardView(evidence);
      const facts = view
        ? [`读了 ${view.pages.filter((p) => p.ok).length} 家`, `${view.priorities.length} 条要点`, `${view.keywords.reduce((n, c) => n + c.items.length, 0)} 个关键词`, view.gaps.length > 0 ? `缺 ${view.gaps.length} 项事实` : ""].filter(Boolean)
        : [firstSentence(card.conclusion)];
      return { headline: sku || text(evidence.product_name) || card.title, facts };
    }
    case "digest": {
      const view = digestCardView(evidence);
      const warns = view ? view.findings.filter((f) => f.severity === "warn").length : 0;
      const facts = view ? [view.dayFrom && view.dayTo ? `${view.dayFrom} ~ ${view.dayTo}` : "", warns > 0 ? `${warns} 条要看的异常` : "没有异常", `${view.sections.length} 节`].filter(Boolean) : [firstSentence(card.conclusion)];
      return { headline: view?.week ? `${view.week} 运营看板` : card.title, facts };
    }
    default: {
      const step = text(evidence.step);
      return { headline: sku ? `${sku}${step ? ` · 卡在 ${step}` : ""}` : card.title, facts: [firstSentence(card.conclusion)] };
    }
  }
}

export function confidenceLabel(value: string): string {
  return value === "high" ? "把握高" : value === "low" ? "把握低" : "把握中";
}

/** 等了多久:给待批的卡看;定下来的卡给「什么时候定的」。 */
export function waitedText(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "";
  const at = new Date(iso).getTime();
  if (!Number.isFinite(at)) return "";
  const minutes = Math.max(0, Math.round((now - at) / 60000));
  if (minutes < 60) return minutes < 2 ? "刚发的" : `等了 ${minutes} 分钟`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `等了 ${hours} 小时`;
  return `等了 ${Math.round(hours / 24)} 天`;
}
