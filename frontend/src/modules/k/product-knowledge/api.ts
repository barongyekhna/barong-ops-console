"use client";

import type {
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
