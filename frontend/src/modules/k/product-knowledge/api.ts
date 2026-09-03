"use client";

import type {
  CategorySpecField,
  CategorySpecTemplate,
  KMediaAsset,
  KMediaCreatePayload,
  KImportISystemImagePayload,
  KImportISystemImageResponse,
  KMediaListResponse,
  ProductKnowledgeVariant,
  ProductReadinessState,
  ProductSectionState,
  KRiskReviewPayload,
  KWorkflowControlPayload,
  KWorkflowExecution,
  KWorkflowExportResponse,
  KWorkflowStartPayload,
  ProductKnowledgeCreatePayload,
  ProductKnowledgeDetail,
  ProductKnowledgeListResponse,
  ProductKnowledgeUpdatePayload,
  KCategoryTree,
  SpecPasteParseResponse,
  WShippingClassOption,
} from "./types";
import type { ProductSellingPoints } from "@/modules/k14/selling-points/types";
import { ApiError, apiRequest } from "@/lib/api";
import { parsePublishGateConflictDetail } from "./publish-gate-error";

export const K_PRODUCTS_PATH = "/k/products";
export const PRODUCT_CREATE_FAILURE_MESSAGE =
  "产品创建失败，请稍后重试或检查SKU/变体信息";


// 只剩给后端返回的图片路径加代理前缀在用（不是发请求）：后端给的是
// `/k/media/…`，浏览器要走代理才拿得到，少这个前缀图片全是裂的。
const API_PROXY_BASE = "/api/backend";

const K_FALLBACK_MESSAGE = "产品知识库请求未完成。";

function asDetailRecord(detail: unknown): Record<string, unknown> | null {
  return detail && typeof detail === "object" && !Array.isArray(detail)
    ? (detail as Record<string, unknown>)
    : null;
}

/**
 * K 的请求入口。传输层全在 `lib/api.ts`（超时、GET 重试、401 派发、
 * K 专属的后端文案翻译 —— `translateKBackendError` 本来就在那里按 `/k/`
 * 前缀调用）；这里只保留 K **特有**的两件事：
 *
 *   1. 模块兜底文案。不传的话失败会退化成通用的「服务暂时不可用」，
 *      不说是哪个模块出的事。
 *   2. **上架门禁 409 的白名单校验。** `parsePublishGateConflictDetail`
 *      只放行完全符合安全形状的 detail（多一个字段、blockers 里混进数字，
 *      一律返回 null）。后端 detail 是不可信输入，这层不能省 ——
 *      收口前它在 errorPayloadFor 里，现在挪到这里，行为一字不变。
 */
async function kRequest<T>(
  path: string,
  options: {
    body?: unknown;
    headers?: HeadersInit;
    method?: string;
    timeoutMs?: number;
  } = {},
): Promise<T> {
  try {
    return await apiRequest<T>(path, {
      ...options,
      fallbackMessage: K_FALLBACK_MESSAGE,
    });
  } catch (error) {
    if (!(error instanceof ApiError)) {
      throw error;
    }
    const publishGateDetail = parsePublishGateConflictDetail(error.detail);
    if (publishGateDetail) {
      throw new ProductKnowledgeApiError(
        "产品未通过上架门禁。",
        error.status,
        publishGateDetail,
      );
    }
    throw new ProductKnowledgeApiError(
      error.message,
      error.status,
      asDetailRecord(error.detail),
    );
  }
}

/**
 * 「没有就是没有」的 GET：404 不是错误，返回 null。
 *
 * 收口前这三处各自写着 `if (response.status === 404) return null;`。
 * `apiRequest` 对 !ok 一律抛 ApiError，所以这层要显式接住。
 * 只接 404 —— 其余状态照常抛，别把「服务挂了」也吞成「没有数据」。
 * （`isRetryableError` 只重试 5xx 和 429，404 不会被重试。）
 */
async function kRequestOrNull<T>(
  path: string,
  options: { method?: string; timeoutMs?: number } = {},
): Promise<T | null> {
  try {
    return await kRequest<T>(path, options);
  } catch (error) {
    if (
      error instanceof ProductKnowledgeApiError &&
      error.status === 404
    ) {
      return null;
    }
    throw error;
  }
}

export class ProductKnowledgeApiError extends Error {
  // 显式字段，不用 TS 的「参数属性」简写 —— 那个需要编译器生成赋值代码，
  // node 的 strip-only 类型剥离做不到，整个模块就 import 不进 `node --test`。
  readonly status: number;
  readonly detail: Record<string, unknown> | null;

  constructor(
    message: string,
    status: number,
    detail: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.name = "ProductKnowledgeApiError";
    this.status = status;
    this.detail = detail;
  }

  get code() {
    return typeof this.detail?.code === "string" ? this.detail.code : null;
  }

  get reason() {
    return typeof this.detail?.reason === "string" ? this.detail.reason : null;
  }
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableJson(item)).join(",")}]`;
  }

  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`)
    .join(",")}}`;
}

function hashString(value: string) {
  let hash = 0x811c9dc5;

  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }

  return hash.toString(16).padStart(8, "0");
}

function productCreateIdempotencyKey(payload: ProductKnowledgeCreatePayload) {
  return `k-product-create-${hashString(stableJson(payload))}`;
}

export async function getProducts(options?: {
  limit?: number;
  offset?: number;
  q?: string;
}): Promise<ProductKnowledgeListResponse> {
  const params = new URLSearchParams();
  if (options?.limit) {
    params.set("limit", String(options.limit));
  }
  if (options?.offset) {
    params.set("offset", String(options.offset));
  }
  if (options?.q?.trim()) {
    params.set("q", options.q.trim());
  }
  const path = `${K_PRODUCTS_PATH}${params.toString() ? `?${params.toString()}` : ""}`;
  return kRequest<ProductKnowledgeListResponse>(path);
}

export async function getProduct(
  productId: string,
): Promise<ProductKnowledgeDetail> {
  const path = `${K_PRODUCTS_PATH}/${encodeURIComponent(productId)}`;
  return kRequest<ProductKnowledgeDetail>(path);
}

export async function getShippingClasses(): Promise<WShippingClassOption[]> {
  const path = "/w/shipping/classes";
  return kRequest<WShippingClassOption[]>(path);
}

export async function assignProductShipping(productId: string): Promise<unknown> {
  const path = `/w/shipping/assign/${encodeURIComponent(productId)}`;
  return kRequest<unknown>(path, {
    body: { force: true },
    method: "POST",
  });
}

export async function patchProductShipping(
  productId: string,
  payload:
    | {
        clear_review: boolean;
        shipping_class_slug: string | null;
      }
    | { contains_battery: boolean },
): Promise<unknown> {
  const path = `/w/shipping/products/${encodeURIComponent(productId)}`;
  return kRequest<unknown>(path, {
    body: payload,
    method: "PATCH",
  });
}

export async function createProduct(
  payload: ProductKnowledgeCreatePayload,
): Promise<ProductKnowledgeDetail> {
  const path = K_PRODUCTS_PATH;
  return kRequest<ProductKnowledgeDetail>(path, {
    body: payload,
    headers: { "Idempotency-Key": productCreateIdempotencyKey(payload) },
    method: "POST",
  });
}

export async function updateProduct(
  productId: string,
  payload: ProductKnowledgeUpdatePayload,
): Promise<ProductKnowledgeDetail> {
  const path = `${K_PRODUCTS_PATH}/${encodeURIComponent(productId)}`;
  return kRequest<ProductKnowledgeDetail>(path, {
    body: payload,
    method: "PATCH",
  });
}

export async function updateVariantPrices(
  productId: string,
  items: { variant_id: string; price_override: number }[],
): Promise<{ items: ProductKnowledgeVariant[]; count: number }> {
  const path = `${K_PRODUCTS_PATH}/${encodeURIComponent(productId)}/variant-prices`;
  return kRequest<{ items: ProductKnowledgeVariant[]; count: number }>(path, {
    body: { items },
    method: "PATCH",
  });
}

export async function deleteProduct(
  productId: string,
  productKey: string,
): Promise<{
  status: "deleted";
  product_id: string;
  product_key: string;
  deleted_counts: Record<string, number>;
}> {
  const path = `${K_PRODUCTS_PATH}/${encodeURIComponent(productId)}`;
  return kRequest<{ status: "deleted"; product_id: string; product_key: string; deleted_counts: Record<string, number>; }>(path, {
    body: { product_key: productKey },
    method: "DELETE",
  });
}

export async function enrichProductWithDeepSeek(
  productId: string,
): Promise<void> {
  const path = `${K_PRODUCTS_PATH}/${productId}/enrich/deepseek`;
  await kRequest<unknown>(path, {
    method: "POST",
  });
}

/**
 * 把卖点生成排进后台队列，立即返回。
 *
 * 2026-08-03 之前这里是同步等后端跑完两次串行 DeepSeek 调用（实测中位数
 * 100s、最慢 903s），刷新页面就白等。现在返回 job，由调用方轮
 * `getGenerationJobs` 看 `stage` 分步显示。
 */
export async function generateProductSellingPoints(
  productId: string,
): Promise<GenerationEnqueueResult> {
  const path = `${K_PRODUCTS_PATH}/${productId}/selling-points/generate`;
  return kRequest<GenerationEnqueueResult>(path, {
    method: "POST",
  });
}

export async function approveProductSellingPoints(
  productId: string,
  payload: ProductSellingPoints,
): Promise<ProductSellingPoints> {
  const path = `${K_PRODUCTS_PATH}/${productId}/selling-points/approve`;
  return kRequest<ProductSellingPoints>(path, {
    body: payload,
    method: "POST",
  });
}

export async function getProductSellingPoints(
  productId: string,
): Promise<ProductSellingPoints | null> {
  const path = `${K_PRODUCTS_PATH}/${productId}/selling-points`;
  return kRequestOrNull<ProductSellingPoints>(path);
}

/** 多阶段任务的进度。目前只有卖点生成用（bullets → zh → copy → done）。 */
export type GenerationStage = "bullets" | "zh" | "copy" | "done";

export type GenerationJob = {
  job_id: string;
  product_id: string;
  job_type: string;
  status: string;
  error: string | null;
  skill_version: string | null;
  /** 单阶段任务恒为 null。 */
  stage?: GenerationStage | string | null;
  /** 某个增强阶段失败时的原因，例如 {"zh": "..."}。卖点本体照常可用。 */
  stage_errors?: Record<string, string> | null;
  /** 入队时命中去重、复用了在途任务——按钮"没反应"其实是"已经在跑"。 */
  deduplicated?: boolean | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type GenerationEnqueueResult = {
  batch_id: string;
  jobs: GenerationJob[];
};

async function enqueueGeneration(
  productId: string,
  kind: "generate-copy" | "generate-image-brief",
): Promise<GenerationEnqueueResult> {
  const path = `${K_PRODUCTS_PATH}/${productId}/${kind}`;
  return kRequest<GenerationEnqueueResult>(path, {
    method: "POST",
  });
}

export function generateProductCopy(productId: string): Promise<GenerationEnqueueResult> {
  return enqueueGeneration(productId, "generate-copy");
}

export function generateProductImageBrief(productId: string): Promise<GenerationEnqueueResult> {
  return enqueueGeneration(productId, "generate-image-brief");
}

async function enqueueGenerationBatch(
  productIds: string[],
  kind: "generate-copy" | "generate-image-brief",
): Promise<GenerationEnqueueResult> {
  const path = `${K_PRODUCTS_PATH}/${kind}/batch`;
  return kRequest<GenerationEnqueueResult>(path, {
    body: { product_ids: productIds },
    method: "POST",
  });
}

export function generateProductCopyBatch(
  productIds: string[],
): Promise<GenerationEnqueueResult> {
  return enqueueGenerationBatch(productIds, "generate-copy");
}

export function generateProductImageBriefBatch(
  productIds: string[],
): Promise<GenerationEnqueueResult> {
  return enqueueGenerationBatch(productIds, "generate-image-brief");
}

export async function getGenerationJobs(productId: string): Promise<GenerationJob[]> {
  const path = `${K_PRODUCTS_PATH}/${productId}/generation-jobs`;
  const data = await kRequest<{ jobs: GenerationJob[] }>(path);
  return data.jobs ?? [];
}

/**
 * 作图底板：能当底图用的实拍参考图。
 *
 * pose 决定它适合当哪类成品图的底板——产品的姿态在照片里就定死了，事后改不
 * 了，所以「软管展开、正在被使用」的那张只能靠实拍拿到。
 */
export type ImagePlate = {
  asset_id: string;
  pose: "in_use" | "product_only" | "accessories" | "detail";
  has_mask: boolean;
  mask_asset_id: string | null;
  width: number | null;
  height: number | null;
  file_url: string;
  preview_url: string;
  thumbnail_url: string;
};

export async function getImagePlates(
  productId: string,
): Promise<{ items: ImagePlate[]; masked_count: number }> {
  const path = `${K_PRODUCTS_PATH}/${productId}/image-plates`;
  const data = await kRequest<{ items: ImagePlate[]; masked_count: number }>(path);
  // 后端给的是它自己的路径（/k/media/…）。浏览器要走代理才拿得到，
  // 少这个前缀图片就全是裂的。前缀是 API 层的事，别让组件各拼各的。
  return {
    ...data,
    items: (data.items ?? []).map((item) => ({
      ...item,
      file_url: `${API_PROXY_BASE}${item.file_url}`,
      preview_url: `${API_PROXY_BASE}${item.preview_url}`,
      thumbnail_url: `${API_PROXY_BASE}${item.thumbnail_url}`,
    })),
  };
}

/** 保存某张底图的产品保护蒙版（画笔导出的 PNG）。覆盖式，一张底图只留一份。 */
export async function savePlateMask(
  productId: string,
  assetId: string,
  maskPngBase64: string,
): Promise<{ mask_asset_id: string; bytes: number }> {
  const path = `${K_PRODUCTS_PATH}/${productId}/image-plates/${assetId}/mask`;
  return kRequest<{ mask_asset_id: string; bytes: number }>(path, {
    body: { mask_png_base64: maskPngBase64 },
    method: "PUT",
  });
}

/** 「这个产品怎么工作」——AI 看原厂参考图推导，人工可改。作图/渲染/审查共用。 */
export type OperatingModel = {
  how_it_works: string;
  hard_constraints: string[];
  forbidden_depictions: string[];
  buyer_personas: string[];
  edited_by_user?: boolean;
  derived_at?: string | null;
  edited_at?: string | null;
};

export async function updateOperatingModel(
  productId: string,
  payload: {
    how_it_works: string;
    hard_constraints: string[];
    forbidden_depictions: string[];
    buyer_personas: string[];
  },
): Promise<OperatingModel> {
  const path = `${K_PRODUCTS_PATH}/${productId}/operating-model`;
  const data = await kRequest<{ operating_model: OperatingModel }>(path, {
    body: payload,
    method: "PUT",
  });
  return data.operating_model;
}

export type RenderJob = {
  job_id: string;
  batch_id: string;
  position: number;
  placement: string;
  role_label: string | null;
  asset_role: string;
  status: string;
  error: string | null;
  asset_id: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type RenderJobsSummary = {
  total: number;
  pending: number;
  running: number;
  completed: number;
  failed: number;
};

export type RenderJobsResult = {
  batch_id: string | null;
  jobs: RenderJob[];
  summary: RenderJobsSummary;
};

export type RenderEnqueueResult = {
  batch_id: string;
  jobs: RenderJob[];
};

export async function renderProductImages(
  productId: string,
  positions?: number[],
): Promise<RenderEnqueueResult> {
  const path = `${K_PRODUCTS_PATH}/${productId}/render-images`;
  return kRequest<RenderEnqueueResult>(path, {
    body: positions && positions.length ? { positions } : {},
    method: "POST",
  });
}

export async function getRenderJobs(
  productId: string,
  batchId?: string,
): Promise<RenderJobsResult> {
  const query = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : "";
  const path = `${K_PRODUCTS_PATH}/${productId}/render-jobs${query}`;
  return kRequest<RenderJobsResult>(path);
}

export async function retryRenderJobs(
  productId: string,
  batchId: string,
): Promise<RenderJobsResult> {
  const path = `${K_PRODUCTS_PATH}/${productId}/render-images/retry`;
  return kRequest<RenderJobsResult>(path, {
    body: { batch_id: batchId },
    method: "POST",
  });
}

export type ProductFaqItem = { question: string; answer: string };

export async function updateProductFaq(
  productId: string,
  items: ProductFaqItem[],
): Promise<{
  page_faq: ProductFaqItem[];
  faq_schema_eligible: boolean;
}> {
  const path = `${K_PRODUCTS_PATH}/${encodeURIComponent(productId)}/faq`;
  return kRequest(path, { body: { items }, method: "PUT" });
}

export type RepublishStage = "auditing" | "exporting" | "dispatching";

/** 一键重推：改完内容后重新上架同一产品（SKU upsert 原地更新，链接不变）。
 * 串起既有三步：品牌审查（等出新结果且 clean）→ 导出 → 派单。
 * 任一环失败即抛错并带清晰的下一步指引；绝不绕过品牌硬门。 */
export async function republishProduct(
  productId: string,
  onStage?: (stage: RepublishStage) => void,
): Promise<DispatchUploadResult> {
  type AuditSnapshot = {
    clean?: boolean | null;
    audited_at?: string | null;
    text_violations?: unknown[] | null;
    image_violations?: unknown[] | null;
  };
  const readAudit = (detail: unknown): AuditSnapshot | null => {
    const value = (detail as { brand_audit_json?: AuditSnapshot | null })
      .brand_audit_json;
    return value && typeof value === "object" ? value : null;
  };
  onStage?.("auditing");
  const before = readAudit(await getProduct(productId));
  await runBrandAudit(productId);
  // 审查是异步任务：以 audited_at 变化判定"新结果"，避免读到旧快照。
  const deadline = Date.now() + 240_000;
  let audit: AuditSnapshot | null = null;
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 8_000));
    audit = readAudit(await getProduct(productId));
    if (audit?.audited_at && audit.audited_at !== before?.audited_at) {
      break;
    }
    if (Date.now() > deadline) {
      throw new Error(
        "品牌审查排队超时——稍后到详情页「品牌审查」面板确认结果后再点重推。",
      );
    }
  }
  if (audit?.clean !== true) {
    const textCount = audit?.text_violations?.length ?? 0;
    const imageCount = audit?.image_violations?.length ?? 0;
    throw new Error(
      `品牌审查未通过（文本 ${textCount} 项 / 图片 ${imageCount} 项）` +
        "——到产品详情「品牌审查」面板处理违规后再重推。",
    );
  }
  onStage?.("exporting");
  await exportWorkflow(productId);
  onStage?.("dispatching");
  return dispatchUpload(productId);
}

export function runBrandAudit(productId: string): Promise<GenerationEnqueueResult> {
  return enqueueGeneration(
    productId,
    "brand-audit" as "generate-copy" | "generate-image-brief",
  );
}

export type BrandFindingIgnore = {
  kind: "text" | "image";
  ignored: boolean;
  surface?: string | null;
  term?: string | null;
  position?: number | null;
  category?: string | null;
};

export async function ignoreBrandFinding(
  productId: string,
  payload: BrandFindingIgnore,
): Promise<{ brand_audit_json: unknown; fingerprint: string }> {
  const path = `${K_PRODUCTS_PATH}/${productId}/brand-audit/ignore`;
  return kRequest<{ brand_audit_json: unknown; fingerprint: string }>(path, {
    body: payload,
    method: "POST",
  });
}

/**
 * 人工放行整个产品的品牌审查。
 *
 * 2026-08-11 用户拍板：审查器是 AI，它不真正了解产品——花洒手柄上的 "STOP"
 * （一键止水标识）被判成品牌字样。人做了决定之后，任何程序不得再拦。
 */
export async function setBrandAuditOverride(
  productId: string,
  enabled: boolean,
  reason = "",
): Promise<{ operator_override: unknown }> {
  const path = `${K_PRODUCTS_PATH}/${productId}/brand-audit/override`;
  return kRequest<{ operator_override: unknown }>(path, {
    body: { enabled, reason },
    method: "POST",
  });
}

/** 点「唤起 Codex 作图」预填进 Codex 输入框的指令(与后端 codex_prompt_for_sku 同文案)。 */
export function codexPromptForSku(sku: string): string {
  return (
    `用 barong_k_images:先 k_get_image_brief 取 ${sku} 的简报,再 k_get_reference_images ` +
    "取全部参考图并下载到本地。按简报逐位出图(缺哪位出哪位;已保存的位不动)," +
    "产品像素以参考图为准不许改结构,严格遵守简报里的工作原理与配件清单。" +
    "每张出完先对照参考图自查,再 k_submit_image 交上去;交完等 2 分钟用 " +
    "k_get_submission_status 看审查,被打回的位按报告改了重交,直到干净。" +
    "最后汇报每一位的状态。"
  );
}

export type RenderAsset = {
  asset_id: string;
  position: number;
  placement: string;
  asset_role: string;
  status: string; // staged | available
  role_label: string | null;
  variant_color: string | null;
  staged_at: string | null;
  /** "mcp" = 外部精修通道(Codex 等代理)交回来的稿;worker 渲染的为 null。 */
  submitted_via?: string | null;
  /** 外部稿是谁交的(用户名);worker 渲染的为 null。 */
  submitted_by?: string | null;
};

export async function getRenderAssets(productId: string): Promise<RenderAsset[]> {
  const path = `${K_PRODUCTS_PATH}/${productId}/render-assets`;
  const data = await kRequest<{ assets: RenderAsset[] }>(path);
  return data.assets ?? [];
}

export async function saveRenderAssets(
  productId: string,
  assetIds?: string[],
): Promise<RenderAsset[]> {
  const path = `${K_PRODUCTS_PATH}/${productId}/render-assets/save`;
  const data = await kRequest<{ assets: RenderAsset[] }>(path, {
    body: assetIds && assetIds.length ? { asset_ids: assetIds } : {},
    method: "POST",
  });
  return data.assets ?? [];
}

export async function reworkRenderAsset(
  productId: string,
  payload: {
    asset_id: string;
    extra_prompt: string;
    use_current_as_reference: boolean;
    reference_image_url?: string | null;
    reference_asset_id?: string | null;
  },
): Promise<RenderEnqueueResult> {
  const path = `${K_PRODUCTS_PATH}/${productId}/render-rework`;
  return kRequest<RenderEnqueueResult>(path, {
    body: payload,
    method: "POST",
  });
}

export async function addBriefImage(
  productId: string,
  payload: {
    scene: string;
    placement: "gallery" | "description";
    reference_image_url?: string | null;
    reference_asset_id?: string | null;
  },
): Promise<RenderEnqueueResult> {
  const path = `${K_PRODUCTS_PATH}/${productId}/brief-images`;
  return kRequest<RenderEnqueueResult>(path, {
    body: payload,
    method: "POST",
  });
}

// 把一张手动上传的图标记「绑定(取图)」或取消。绑定的手动图会随渲染图进 P 上架包。
export async function setImageUploadBound(
  productId: string,
  assetId: string,
  bound: boolean,
): Promise<KMediaAsset> {
  const path = `${K_PRODUCTS_PATH}/${productId}/images/${assetId}/upload-bound`;
  return kRequest<KMediaAsset>(path, {
    body: { bound },
    method: "POST",
  });
}

export type OverlayFieldOption = {
  field: string;
  label: string;
  value_text: string;
};

export async function getOverlayFields(
  productId: string,
): Promise<OverlayFieldOption[]> {
  const path = `${K_PRODUCTS_PATH}/${productId}/overlay-fields`;
  const data = await kRequest<{ fields: OverlayFieldOption[] }>(path);
  return data.fields ?? [];
}

export async function applyBriefOverlay(
  productId: string,
  position: number,
  sourceFields: string[],
): Promise<RenderEnqueueResult> {
  const path = `${K_PRODUCTS_PATH}/${productId}/brief-images/${position}/overlay`;
  return kRequest<RenderEnqueueResult>(path, {
    body: { source_fields: sourceFields },
    method: "POST",
  });
}

export type DispatchUploadResult = {
  job_id: string;
  status: string;
  dispatched: boolean;
};

export async function dispatchUpload(
  productId: string,
): Promise<DispatchUploadResult> {
  const path = `/p/products/${encodeURIComponent(productId)}/dispatch`;
  return kRequest<DispatchUploadResult>(path, {
    method: "POST",
  });
}

export async function getProductReadiness(
  productId: string,
): Promise<ProductReadinessState> {
  const path = `${K_PRODUCTS_PATH}/${productId}/readiness`;
  return kRequest<ProductReadinessState>(path);
}

export async function submitProductKeywords(
  productId: string,
): Promise<ProductSectionState> {
  const path = `${K_PRODUCTS_PATH}/${productId}/keywords/submit`;
  return kRequest<ProductSectionState>(path, {
    method: "POST",
  });
}

export async function getLatestWorkflow(
  productId: string,
): Promise<KWorkflowExecution | null> {
  const path = `${K_PRODUCTS_PATH}/${productId}/workflow/latest`;
  return kRequestOrNull<KWorkflowExecution>(path);
}

export async function startWorkflow(
  productId: string,
  payload: KWorkflowStartPayload,
): Promise<KWorkflowExecution> {
  const path = `${K_PRODUCTS_PATH}/${productId}/workflow/start`;
  return kRequest<KWorkflowExecution>(path, {
    body: payload,
    method: "POST",
  });
}

export async function reviewWorkflowRiskTerms(
  productId: string,
  payload: KRiskReviewPayload,
): Promise<KWorkflowExecution> {
  const path = `${K_PRODUCTS_PATH}/${productId}/workflow/risk-review`;
  return kRequest<KWorkflowExecution>(path, {
    body: payload,
    method: "POST",
  });
}

export async function exportWorkflow(
  productId: string,
  executionId?: string | null,
): Promise<KWorkflowExportResponse> {
  const path = `${K_PRODUCTS_PATH}/${productId}/workflow/export`;
  return kRequest<KWorkflowExportResponse>(path, {
    body: { execution_id: executionId ?? null },
    method: "POST",
  });
}

export async function controlWorkflow(
  productId: string,
  action: "pause" | "resume" | "retry" | "rollback",
  payload: KWorkflowControlPayload,
): Promise<KWorkflowExecution> {
  const path = `${K_PRODUCTS_PATH}/${productId}/workflow/${action}`;
  return kRequest<KWorkflowExecution>(path, {
    body: payload,
    method: "POST",
  });
}

export async function getMediaAssets(
  productId: string,
): Promise<KMediaListResponse> {
  const path = `/k/media?product_id=${encodeURIComponent(productId)}`;
  return kRequest<KMediaListResponse>(path);
}

export async function createMediaAsset(
  payload: KMediaCreatePayload,
): Promise<KMediaAsset> {
  const path = "/k/media";
  return kRequest<KMediaAsset>(path, {
    body: payload,
    method: "POST",
  });
}

export async function deleteMediaAsset(assetId: string): Promise<KMediaAsset> {
  const path = `/k/media/${assetId}`;
  return kRequest<KMediaAsset>(path, {
    method: "DELETE",
  });
}

export function mediaAssetFileUrl(assetId: string) {
  return `${API_PROXY_BASE}/k/media/${encodeURIComponent(assetId)}/file`;
}

export function mediaAssetThumbnailUrl(assetId: string) {
  return `${API_PROXY_BASE}/k/media/${encodeURIComponent(assetId)}/thumbnail`;
}

export function mediaAssetPreviewUrl(assetId: string) {
  return `${API_PROXY_BASE}/k/media/${encodeURIComponent(assetId)}/preview`;
}

export async function uploadProductMediaAsset(
  productId: string,
  file: File,
  variantSku: string,
  assetRole: string = "main",
): Promise<KMediaAsset> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("variant_sku", variantSku);
  formData.append("asset_role", assetRole);

  const path = `${K_PRODUCTS_PATH}/${productId}/media/upload`;
  return kRequest<KMediaAsset>(path, {
    method: "POST",
  });
}

export async function submitProductImages(
  productId: string,
): Promise<ProductSectionState> {
  const path = `${K_PRODUCTS_PATH}/${productId}/images/submit`;
  return kRequest<ProductSectionState>(path, {
    method: "POST",
  });
}

export async function bindProductImage(
  productId: string,
  payload:
    | { source_type: "manual_upload_image"; asset_id: string; variant_sku: string }
    | {
        source_type: "i_system_asset";
        i_system_image_asset_id: string;
        variant_sku: string;
      },
): Promise<KWorkflowExecution> {
  const path = `${K_PRODUCTS_PATH}/${productId}/images/bind`;
  return kRequest<KWorkflowExecution>(path, {
    body: payload,
    method: "POST",
  });
}

export async function importISystemImagesToProduct(
  productId: string,
  payload: KImportISystemImagePayload,
): Promise<KImportISystemImageResponse> {
  const path = `${K_PRODUCTS_PATH}/${encodeURIComponent(productId)}/images/import-i-output`;
  return kRequest<KImportISystemImageResponse>(path, {
    body: payload,
    method: "POST",
  });
}

function categorySpecTemplatePath(
  categoryTree: KCategoryTree,
  categoryId: string,
  suffix = "",
) {
  const params = new URLSearchParams({ tree: categoryTree });
  return `/k/categories/${encodeURIComponent(
    categoryId,
  )}/spec-template${suffix}?${params.toString()}`;
}

export async function getCategorySpecTemplate(
  categoryTree: KCategoryTree,
  categoryId: string,
): Promise<CategorySpecTemplate | null> {
  const path = categorySpecTemplatePath(categoryTree, categoryId);
  return kRequestOrNull<CategorySpecTemplate>(path);
}

export async function draftCategorySpecTemplate(
  categoryTree: KCategoryTree,
  categoryId: string,
): Promise<CategorySpecTemplate> {
  const path = categorySpecTemplatePath(categoryTree, categoryId, "/draft");
  return kRequest<CategorySpecTemplate>(path, {
    method: "POST",
  });
}

export async function putCategorySpecTemplate(
  categoryTree: KCategoryTree,
  categoryId: string,
  payload: {
    status: CategorySpecTemplate["status"];
    fields: CategorySpecField[];
  },
): Promise<CategorySpecTemplate> {
  const path = categorySpecTemplatePath(categoryTree, categoryId);
  return kRequest<CategorySpecTemplate>(path, {
    body: payload,
    method: "PUT",
  });
}

export async function parseProductSpecsPaste(
  productId: string,
  rawText: string,
): Promise<SpecPasteParseResponse> {
  const path = `${K_PRODUCTS_PATH}/${encodeURIComponent(productId)}/specs/parse-paste`;
  return kRequest<SpecPasteParseResponse>(path, {
    body: { raw_text: rawText },
    method: "POST",
  });
}

export type CategoryTreeItem = {
  id: string;
  name: string;
  full_path: string;
  level: number;
  is_leaf: boolean;
};

export async function searchCategories(
  tree: "google" | "amazon",
  q: string,
  limit = 30,
): Promise<CategoryTreeItem[]> {
  const params = new URLSearchParams({ tree, q, limit: String(limit) });
  const path = `/k/categories/search?${params.toString()}`;
  const data = await kRequest<{ items: CategoryTreeItem[] }>(path);
  return data.items ?? [];
}
