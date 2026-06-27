"use client";

import type {
  KMediaAsset,
  KMediaCreatePayload,
  KMediaListResponse,
  KRiskReviewPayload,
  KWorkflowControlPayload,
  KWorkflowExecution,
  KWorkflowExportResponse,
  KWorkflowStartPayload,
  ProductKnowledgeCreatePayload,
  ProductKnowledgeDetail,
  ProductKnowledgeListResponse,
  ProductKnowledgeUpdatePayload,
} from "./types";
import type { ProductSellingPoints } from "@/modules/k14/selling-points/types";
import { translateKBackendError } from "@/lib/i18n";

const API_PROXY_BASE = "/api/backend";
export const K_PRODUCTS_PATH = "/k/products";
export const PRODUCT_CREATE_FAILURE_MESSAGE =
  "产品创建失败，请稍后重试或检查SKU/变体信息";

const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

export class ProductKnowledgeApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.name = "ProductKnowledgeApiError";
  }

  get code() {
    return typeof this.detail?.code === "string" ? this.detail.code : null;
  }

  get reason() {
    return typeof this.detail?.reason === "string" ? this.detail.reason : null;
  }
}

function readAccessToken() {
  if (typeof window === "undefined") {
    return null;
  }

  return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
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

function buildHeaders(hasBody = false, idempotencyKey?: string) {
  const headers = new Headers({
    Accept: "application/json",
  });
  const accessToken = readAccessToken();

  if (hasBody) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  if (idempotencyKey) {
    headers.set("Idempotency-Key", idempotencyKey);
  }

  return headers;
}

async function errorPayloadFor(
  response: Response,
): Promise<{ detail: Record<string, unknown> | null; message: string }> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return { detail: null, message: payload.detail };
    }
    if (
      payload.detail &&
      typeof payload.detail === "object" &&
      "message" in payload.detail
    ) {
      const detail = payload.detail as Record<string, unknown>;
      const message =
        typeof detail.message === "string"
          ? detail.message
          : "产品知识库请求未完成。";

      return { detail, message };
    }
  } catch {
    // Keep the stable fallback for non-JSON backend responses.
  }

  return { detail: null, message: "产品知识库请求未完成。" };
}

async function readJson<T>(response: Response, path: string): Promise<T> {
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }

  if (!response.ok) {
    const errorPayload = await errorPayloadFor(response);
    throw new ProductKnowledgeApiError(
      translateKBackendError({
        detail: errorPayload.detail,
        fallback: "产品知识库请求未完成。",
        message: errorPayload.message,
        path,
        status: response.status,
      }),
      response.status,
      errorPayload.detail,
    );
  }

  return (await response.json()) as T;
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
  const response = await fetch(`${API_PROXY_BASE}${path}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });

  return readJson<ProductKnowledgeListResponse>(response, path);
}

export async function createProduct(
  payload: ProductKnowledgeCreatePayload,
): Promise<ProductKnowledgeDetail> {
  const path = K_PRODUCTS_PATH;
  const response = await fetch(`${API_PROXY_BASE}${path}`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true, productCreateIdempotencyKey(payload)),
    method: "POST",
  });

  return readJson<ProductKnowledgeDetail>(response, path);
}

export async function updateProduct(
  productId: string,
  payload: ProductKnowledgeUpdatePayload,
): Promise<ProductKnowledgeDetail> {
  const path = `${K_PRODUCTS_PATH}/${encodeURIComponent(productId)}`;
  const response = await fetch(
    `${API_PROXY_BASE}${path}`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "PATCH",
    },
  );

  return readJson<ProductKnowledgeDetail>(response, path);
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
  const response = await fetch(
    `${API_PROXY_BASE}${path}`,
    {
      body: JSON.stringify({ product_key: productKey }),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "DELETE",
    },
  );

  return readJson<{
    status: "deleted";
    product_id: string;
    product_key: string;
    deleted_counts: Record<string, number>;
  }>(response, path);
}

export async function enrichProductWithDeepSeek(
  productId: string,
): Promise<void> {
  const path = `${K_PRODUCTS_PATH}/${productId}/enrich/deepseek`;
  const response = await fetch(
    `${API_PROXY_BASE}${path}`,
    {
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );

  await readJson<unknown>(response, path);
}

export async function generateProductSellingPoints(
  productId: string,
): Promise<ProductSellingPoints> {
  const path = `${K_PRODUCTS_PATH}/${productId}/selling-points/generate`;
  const response = await fetch(
    `${API_PROXY_BASE}${path}`,
    {
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );

  return readJson<ProductSellingPoints>(response, path);
}

export async function approveProductSellingPoints(
  productId: string,
  payload: ProductSellingPoints,
): Promise<ProductSellingPoints> {
  const path = `${K_PRODUCTS_PATH}/${productId}/selling-points/approve`;
  const response = await fetch(
    `${API_PROXY_BASE}${path}`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );

  return readJson<ProductSellingPoints>(response, path);
}

export async function getLatestWorkflow(
  productId: string,
): Promise<KWorkflowExecution | null> {
  const path = `${K_PRODUCTS_PATH}/${productId}/workflow/latest`;
  const response = await fetch(
    `${API_PROXY_BASE}${path}`,
    {
      cache: "no-store",
      headers: buildHeaders(),
      method: "GET",
    },
  );

  if (response.status === 404) {
    return null;
  }

  return readJson<KWorkflowExecution>(response, path);
}

export async function startWorkflow(
  productId: string,
  payload: KWorkflowStartPayload,
): Promise<KWorkflowExecution> {
  const path = `${K_PRODUCTS_PATH}/${productId}/workflow/start`;
  const response = await fetch(
    `${API_PROXY_BASE}${path}`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );

  return readJson<KWorkflowExecution>(response, path);
}

export async function reviewWorkflowRiskTerms(
  productId: string,
  payload: KRiskReviewPayload,
): Promise<KWorkflowExecution> {
  const path = `${K_PRODUCTS_PATH}/${productId}/workflow/risk-review`;
  const response = await fetch(
    `${API_PROXY_BASE}${path}`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );

  return readJson<KWorkflowExecution>(response, path);
}

export async function exportWorkflow(
  productId: string,
  executionId?: string | null,
): Promise<KWorkflowExportResponse> {
  const path = `${K_PRODUCTS_PATH}/${productId}/workflow/export`;
  const response = await fetch(
    `${API_PROXY_BASE}${path}`,
    {
      body: JSON.stringify({ execution_id: executionId ?? null }),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );

  return readJson<KWorkflowExportResponse>(response, path);
}

export async function controlWorkflow(
  productId: string,
  action: "pause" | "resume" | "retry" | "rollback",
  payload: KWorkflowControlPayload,
): Promise<KWorkflowExecution> {
  const path = `${K_PRODUCTS_PATH}/${productId}/workflow/${action}`;
  const response = await fetch(
    `${API_PROXY_BASE}${path}`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );

  return readJson<KWorkflowExecution>(response, path);
}

export async function getMediaAssets(
  productId: string,
): Promise<KMediaListResponse> {
  const path = `/k/media?product_id=${encodeURIComponent(productId)}`;
  const response = await fetch(`${API_PROXY_BASE}${path}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });

  return readJson<KMediaListResponse>(response, path);
}

export async function createMediaAsset(
  payload: KMediaCreatePayload,
): Promise<KMediaAsset> {
  const path = "/k/media";
  const response = await fetch(`${API_PROXY_BASE}${path}`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });

  return readJson<KMediaAsset>(response, path);
}

export async function deleteMediaAsset(assetId: string): Promise<KMediaAsset> {
  const path = `/k/media/${assetId}`;
  const response = await fetch(`${API_PROXY_BASE}${path}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "DELETE",
  });

  return readJson<KMediaAsset>(response, path);
}

export function mediaAssetFileUrl(assetId: string) {
  return `${API_PROXY_BASE}/k/media/${encodeURIComponent(assetId)}/file`;
}

export async function uploadProductMediaAsset(
  productId: string,
  file: File,
  variantSku: string,
): Promise<KMediaAsset> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("variant_sku", variantSku);
  formData.append("asset_role", "main");

  const path = `${K_PRODUCTS_PATH}/${productId}/media/upload`;
  const response = await fetch(
    `${API_PROXY_BASE}${path}`,
    {
      body: formData,
      cache: "no-store",
      headers: buildHeaders(),
      method: "POST",
    },
  );

  return readJson<KMediaAsset>(response, path);
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
  const response = await fetch(
    `${API_PROXY_BASE}${path}`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );

  return readJson<KWorkflowExecution>(response, path);
}
