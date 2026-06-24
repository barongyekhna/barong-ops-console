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
} from "./types";

const API_PROXY_BASE = "/api/backend";
export const K_PRODUCTS_PATH = "/k/products";

const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

export class ProductKnowledgeApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ProductKnowledgeApiError";
  }
}

function readAccessToken() {
  if (typeof window === "undefined") {
    return null;
  }

  return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
}

function buildHeaders(hasBody = false) {
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

  return headers;
}

async function errorMessageFor(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (
      payload.detail &&
      typeof payload.detail === "object" &&
      "message" in payload.detail
    ) {
      const detail = payload.detail as { code?: unknown; message?: unknown };
      const code = typeof detail.code === "string" ? `${detail.code}: ` : "";
      const message =
        typeof detail.message === "string"
          ? detail.message
          : "The Product Knowledge API request could not be completed.";

      return `${code}${message}`;
    }
  } catch {
    // Keep the stable fallback for non-JSON backend responses.
  }

  return "The Product Knowledge API request could not be completed.";
}

async function readJson<T>(response: Response): Promise<T> {
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }

  if (!response.ok) {
    throw new ProductKnowledgeApiError(
      await errorMessageFor(response),
      response.status,
    );
  }

  return (await response.json()) as T;
}

export async function getProducts(): Promise<ProductKnowledgeListResponse> {
  const response = await fetch(`${API_PROXY_BASE}${K_PRODUCTS_PATH}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });

  return readJson<ProductKnowledgeListResponse>(response);
}

export async function createProduct(
  payload: ProductKnowledgeCreatePayload,
): Promise<ProductKnowledgeDetail> {
  const response = await fetch(`${API_PROXY_BASE}${K_PRODUCTS_PATH}`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });

  return readJson<ProductKnowledgeDetail>(response);
}

export async function getLatestWorkflow(
  productId: string,
): Promise<KWorkflowExecution | null> {
  const response = await fetch(
    `${API_PROXY_BASE}${K_PRODUCTS_PATH}/${productId}/workflow/latest`,
    {
      cache: "no-store",
      headers: buildHeaders(),
      method: "GET",
    },
  );

  if (response.status === 404) {
    return null;
  }

  return readJson<KWorkflowExecution>(response);
}

export async function startWorkflow(
  productId: string,
  payload: KWorkflowStartPayload,
): Promise<KWorkflowExecution> {
  const response = await fetch(
    `${API_PROXY_BASE}${K_PRODUCTS_PATH}/${productId}/workflow/start`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );

  return readJson<KWorkflowExecution>(response);
}

export async function reviewWorkflowRiskTerms(
  productId: string,
  payload: KRiskReviewPayload,
): Promise<KWorkflowExecution> {
  const response = await fetch(
    `${API_PROXY_BASE}${K_PRODUCTS_PATH}/${productId}/workflow/risk-review`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );

  return readJson<KWorkflowExecution>(response);
}

export async function exportWorkflow(
  productId: string,
  executionId?: string | null,
): Promise<KWorkflowExportResponse> {
  const response = await fetch(
    `${API_PROXY_BASE}${K_PRODUCTS_PATH}/${productId}/workflow/export`,
    {
      body: JSON.stringify({ execution_id: executionId ?? null }),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );

  return readJson<KWorkflowExportResponse>(response);
}

export async function controlWorkflow(
  productId: string,
  action: "pause" | "resume" | "retry" | "rollback",
  payload: KWorkflowControlPayload,
): Promise<KWorkflowExecution> {
  const response = await fetch(
    `${API_PROXY_BASE}${K_PRODUCTS_PATH}/${productId}/workflow/${action}`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );

  return readJson<KWorkflowExecution>(response);
}

export async function getMediaAssets(
  productId: string,
): Promise<KMediaListResponse> {
  const response = await fetch(
    `${API_PROXY_BASE}/k/media?product_id=${encodeURIComponent(productId)}`,
    {
      cache: "no-store",
      headers: buildHeaders(),
      method: "GET",
    },
  );

  return readJson<KMediaListResponse>(response);
}

export async function createMediaAsset(
  payload: KMediaCreatePayload,
): Promise<KMediaAsset> {
  const response = await fetch(`${API_PROXY_BASE}/k/media`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });

  return readJson<KMediaAsset>(response);
}

export async function bindProductImage(
  productId: string,
  payload:
    | { source_type: "manual_upload_image"; asset_id: string }
    | { source_type: "i_system_asset"; i_system_image_asset_id: string },
): Promise<KWorkflowExecution> {
  const response = await fetch(
    `${API_PROXY_BASE}${K_PRODUCTS_PATH}/${productId}/images/bind`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );

  return readJson<KWorkflowExecution>(response);
}
