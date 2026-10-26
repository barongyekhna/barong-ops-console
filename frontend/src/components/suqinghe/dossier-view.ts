/**
 * 档案柜:后端档案草稿(draft)→ 界面要画的几块。纯函数,不碰 React,测试直接拿真档案喂。
 *
 * 10-26 之前界面把 draft 最外层的每个键(fields、specs、flagged、version……)都当成一行「字段」,
 * 嵌套的对象被压平成「键：值；键：值」一长串,老板看到的是一墙文字和内部记号;变体表取的字段名
 * (name / cost_cny / dimensions)和后端存的(name_zh / cost_price_cny / dims_cm)对不上,只剩重量一列有数。
 * 这里按后端真实的结构逐块取,认不出的值宁可显示「—」,也绝不摊原始结构。
 */

export type FieldStatus = "ok" | "conflict" | "missing" | "needs_owner";

export type SourceLine = { kind: string; where: string; raw: string };

export type ValueChoice = { value: string; why: string; sources: SourceLine[] };

export type ValueRow = {
  key: string;
  label: string;
  value: string;
  status: FieldStatus;
  statusLabel: string;
  note: string;
  sources: SourceLine[];
  /** 说法不一时各方的值和出处 */
  candidates: ValueChoice[];
  /** 不标红、但图上还有的说法(把握低 / 看不出是不是本品 / 对不上任何规格) */
  alternatives: ValueChoice[];
  /** 按规格不同的值:[规格名, 值] */
  perVariant: Array<[string, string]>;
};

export type VariantRow = {
  nameZh: string;
  nameEn: string;
  cost: string;
  specs: string;
  packWeight: string;
  packDims: string;
  image: string | null;
};

export type DossierViewModel = {
  version: number;
  summary: string;
  attention: ValueRow[];
  basics: ValueRow[];
  specs: ValueRow[];
  variants: VariantRow[];
  pricing: { text: string; mode: string; tiers: Array<{ qty: string; price: string }> };
  otherAttributes: Array<{ name: string; value: string }>;
  supplier: { name: string; detail: string; url: string | null } | null;
  images: string[];
  reading: { text: string; problem: string | null; ignored: string | null };
};

type Rec = Record<string, unknown>;

const isRec = (value: unknown): value is Rec => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const asList = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown): string => (typeof value === "string" ? value.trim() : typeof value === "number" ? String(value) : "");

export const FIELD_LABELS: Record<string, string> = {
  name_zh: "中文原标题",
  name_en: "英文品名",
  category: "谷歌类目",
  product_type: "产品类型",
  moq: "起批量",
  retail_price: "美国售价",
  package_includes: "包装清单",
  detail_images: "详情图",
};

export const SPEC_LABELS: Record<string, string> = {
  material: "材质",
  dimensions: "尺寸(单品)",
  weight: "重量(单品)",
  age_range: "适用年龄",
  color: "颜色",
  packaging: "包装",
  voltage: "电压",
  capacity: "容量",
  power: "功率",
  charging: "充电",
  runtime: "续航",
  cycle_life: "循环次数",
  certification: "认证",
  battery_type: "电池/电芯",
  battery: "电池",
  origin_region: "产地",
  origin_country: "原产国",
  applicable_people: "适用人群",
  weight_pack: "重量(单个包装)",
  dimensions_pack: "尺寸(单个包装)",
  weight_carton: "外箱重量",
  dimensions_carton: "外箱尺寸",
};

const BASIC_ORDER = ["name_zh", "name_en", "category", "product_type", "moq", "retail_price", "package_includes"];

export const STATUS_LABEL: Record<FieldStatus, string> = {
  ok: "",
  conflict: "说法不一",
  missing: "没找到",
  needs_owner: "要你定",
};

const SOURCE_KIND: Record<string, string> = {
  page_json: "页面数据",
  page_text: "页面文字",
  image: "详情图",
  writer: "按事实改写",
  classifier: "类目判定",
  precedent: "店里先例",
};

const CONFIDENCE_LABEL: Record<string, string> = { high: "高", medium: "中", low: "低" };
const PRODUCT_TYPE_LABEL: Record<string, string> = { variable_product: "多规格(变体)", simple_product: "单品" };
const SUPPLIER_TYPE_LABEL: Record<string, string> = { factory: "工厂", trader: "贸易商", company: "公司" };

function withUnit(value: string, unit: unknown): string {
  const u = text(unit);
  if (!value || !u || value === "—") return value;
  return value.toLowerCase().endsWith(u.toLowerCase()) ? value : `${value} ${u}`;
}

/** 草稿里的一个值 → 一句人话。对象只认得出的几种(类目);认不出的显示「—」,绝不摊原始结构。 */
export function displayValue(value: unknown, unit?: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return withUnit(value.trim() || "—", unit);
  if (typeof value === "number") return withUnit(String(value), unit);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) {
    const parts = value.map((item) => displayValue(item)).filter((item) => item !== "—");
    return parts.length ? parts.join("、") : "—";
  }
  if (isRec(value) && ("google_category_id" in value || "path" in value)) {
    const zh = text(value.name_zh);
    const path = text(value.path) || text(value.name);
    const confidence = CONFIDENCE_LABEL[text(value.confidence)];
    const head = [zh, path].filter(Boolean).join(" · ") || "—";
    return confidence ? `${head}(把握:${confidence})` : head;
  }
  return "—";
}

function sourceLines(value: unknown): SourceLine[] {
  return asList(value)
    .filter(isRec)
    .map((source) => {
      const kind = text(source.kind);
      const label = SOURCE_KIND[kind] ?? (kind || "来源");
      const ref = text(source.ref);
      return { kind, where: ref && kind !== "image" ? `${label} · ${ref}` : ref || label, raw: text(source.raw) };
    });
}

function choices(value: unknown, fallbackWhy = ""): ValueChoice[] {
  return asList(value)
    .filter(isRec)
    .map((item) => ({
      value: displayValue(item.value, item.unit),
      why: text(item.why) || fallbackWhy,
      sources: sourceLines(item.sources),
    }));
}

function statusOf(value: unknown): FieldStatus {
  const status = text(value);
  return status === "conflict" || status === "missing" || status === "needs_owner" ? status : "ok";
}

function rowFor(key: string, label: string, field: unknown): ValueRow {
  const rec = isRec(field) ? field : { value: field, status: "ok" };
  const status = statusOf(rec.status);
  let value = displayValue(rec.value, rec.unit);
  if (key === "product_type") value = PRODUCT_TYPE_LABEL[text(rec.value)] ?? value;
  const perVariant = isRec(rec.per_variant)
    ? Object.entries(rec.per_variant).map(([name, v]): [string, string] => [name, displayValue(v)])
    : [];
  return {
    key,
    label,
    value,
    status,
    statusLabel: STATUS_LABEL[status],
    note: text(rec.note),
    sources: sourceLines(rec.sources),
    candidates: choices(rec.candidates),
    alternatives: choices(rec.alternatives),
    perVariant,
  };
}

function fieldRows(fields: unknown): ValueRow[] {
  if (!isRec(fields)) return [];
  const keys = [...BASIC_ORDER.filter((key) => key in fields), ...Object.keys(fields).filter((key) => !BASIC_ORDER.includes(key))];
  return keys.map((key) => rowFor(key, FIELD_LABELS[key] ?? key, fields[key]));
}

function specRows(specs: unknown): ValueRow[] {
  if (!isRec(specs)) return [];
  return Object.entries(specs).map(([key, field]) => rowFor(`specs.${key}`, SPEC_LABELS[key] ?? key, field));
}

const ATTENTION_ORDER: Record<FieldStatus, number> = { conflict: 0, needs_owner: 1, missing: 2, ok: 3 };

function attentionRows(flagged: unknown, basics: ValueRow[], specs: ValueRow[]): ValueRow[] {
  const byKey = new Map([...basics, ...specs].map((row) => [row.key, row]));
  const rows = asList(flagged)
    .filter(isRec)
    .map((flag): ValueRow => {
      const path = text(flag.path);
      const known = byKey.get(path);
      const bare = path.startsWith("specs.") ? path.slice(6) : path;
      const label = text(flag.label) || known?.label || SPEC_LABELS[bare] || FIELD_LABELS[bare] || bare;
      const status = statusOf(flag.status);
      const base = known ?? rowFor(path, label, { value: null, status });
      return { ...base, label, status, statusLabel: STATUS_LABEL[status], note: text(flag.note) || base.note };
    });
  return rows.sort((a, b) => ATTENTION_ORDER[a.status] - ATTENTION_ORDER[b.status]);
}

function money(value: unknown): string {
  const n = typeof value === "number" ? value : Number.parseFloat(text(value));
  return Number.isFinite(n) && n > 0 ? `¥${Number.isInteger(n) ? n : n.toFixed(2).replace(/0$/, "")}` : "—";
}

function variantRows(variants: unknown): VariantRow[] {
  return asList(variants)
    .filter(isRec)
    .map((v) => {
      const dims = asList(v.dims_cm).map((d) => text(d)).filter(Boolean);
      const specs = isRec(v.specs) ? Object.values(v.specs).map((s) => displayValue(s)).filter((s) => s !== "—") : [];
      const weight = text(v.weight_g);
      const image = text(v.image_url);
      return {
        nameZh: text(v.name_zh) || text(v.name) || "—",
        nameEn: text(v.name_en) || "—",
        cost: money(v.cost_price_cny ?? v.price_cny),
        specs: specs.join("、") || "—",
        packWeight: weight ? `${weight} g` : "—",
        packDims: dims.length === 3 ? `${dims.join("×")} cm` : "—",
        image: image.startsWith("https://") ? image : null,
      };
    });
}

function pricingOf(draft: Rec): DossierViewModel["pricing"] {
  const pricing = isRec(draft.pricing) ? draft.pricing : {};
  const tiers = asList(pricing.tiers ?? draft.price_tiers)
    .filter(isRec)
    .map((t) => ({ qty: text(t.min_qty ?? t.begin_amount ?? t.beginAmount) || "—", price: money(t.price_cny ?? t.price) }));
  const mode = text(pricing.mode) || (tiers.length ? "tiers" : "");
  const fallback = tiers.length ? tiers.map((t) => `≥${t.qty}件 ${t.price}`).join("、") : "";
  return { text: text(pricing.text) || fallback || "页面上没拿到进价", mode, tiers };
}

function supplierOf(value: unknown): DossierViewModel["supplier"] {
  if (!isRec(value) || !text(value.name)) return null;
  const parts = [
    SUPPLIER_TYPE_LABEL[text(value.type)] ?? text(value.type),
    text(value.years) ? `入驻 ${text(value.years)} 年` : "",
    text(value.location),
  ].filter(Boolean);
  const url = text(value.shop_url);
  return { name: text(value.name), detail: parts.join(" · "), url: url.startsWith("https://") ? url : null };
}

function readingOf(value: unknown): DossierViewModel["reading"] {
  const r = isRec(value) ? value : {};
  const num = (key: string) => (typeof r[key] === "number" ? (r[key] as number) : Number.parseInt(text(r[key]), 10) || 0);
  const error = text(r.detail_error);
  let line: string;
  if (error) {
    line = "详情图没取到,规格只来自页面数据";
  } else if ("images" in r && num("images") === 0) {
    line = "卖家的详情里没有图片";
  } else {
    const images = num("images");
    line = `${images ? `详情图 ${images} 张,` : ""}读了 ${num("segments_seen")} 段`;
    if (num("images_failed")) line += `,${num("images_failed")} 张打不开`;
  }
  const stopped = text(r.stopped_reason);
  const problem = error || (stopped === "budget" ? "到单份预算上限,后面的图没读" : stopped === "degraded" ? "Claude 当天额度用完,后面的图没读" : null);
  const ignoredParts = [
    num("ignored_other") ? `别的商品 ${num("ignored_other")} 条` : "",
    num("ignored_narrative") ? `广告语 ${num("ignored_narrative")} 条` : "",
    num("ignored_drawing") ? `零件尺寸标注 ${num("ignored_drawing")} 条` : "",
  ].filter(Boolean);
  return { text: line, problem, ignored: ignoredParts.length ? `已排除:${ignoredParts.join("、")}` : null };
}

export function buildDossierView(draft: unknown): DossierViewModel {
  const d = isRec(draft) ? draft : {};
  const basics = fieldRows(d.fields);
  const specs = specRows(d.specs);
  return {
    version: typeof d.version === "number" ? d.version : 1,
    summary: text(d.summary_zh),
    attention: attentionRows(d.flagged, basics, specs),
    basics,
    specs,
    variants: variantRows(d.variants),
    pricing: pricingOf(d),
    otherAttributes: asList(d.other_attributes)
      .filter(isRec)
      .map((a) => ({ name: text(a.name), value: text(a.value) }))
      .filter((a) => a.name && a.value),
    supplier: supplierOf(d.supplier),
    images: asList(d.reference_images)
      .map((item) => (typeof item === "string" ? item : isRec(item) ? text(item.url) : ""))
      .filter((url) => url.startsWith("https://")),
    reading: readingOf(d.image_read),
  };
}
