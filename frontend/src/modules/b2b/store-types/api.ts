"use client";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";
const LABEL = "B2B 店型";

export type OutreachStatus = "idle" | "active" | "paused" | "retired";

export type StoreTypeCategory = {
  id: string;
  category_prefix: string[];
};

export type StoreType = {
  id: string;
  key: string;
  label: string;
  outreach_status: OutreachStatus;
  sort_order: number;
  notes: string | null;
  categories: StoreTypeCategory[];
  total_items: number;
  ready_items: number;
  prospecting_unlocked: boolean;
  shortfall: number;
  prospects_new: number;
  prospects_approved: number;
  newly_added: boolean;
};

export type StoreTypeList = {
  store_types: StoreType[];
  min_ready_items: number;
  max_active: number;
  active_keys: string[];
};

function buildHeaders(json = false) {
  const headers = new Headers({ Accept: "application/json" });
  if (json) {
    headers.set("Content-Type", "application/json");
  }
  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  return headers;
}

async function readJson<T>(response: Response): Promise<T> {
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: string };
      detail = typeof body.detail === "string" ? body.detail : "";
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail || `${LABEL}（${response.status}）`);
  }
  return (await response.json()) as T;
}

export async function getStoreTypes(): Promise<StoreTypeList> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/store-types`, {
    cache: "no-store",
    headers: buildHeaders(),
  });
  return readJson<StoreTypeList>(response);
}

export async function createStoreType(payload: {
  key: string;
  label: string;
}): Promise<StoreType> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/store-types`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<StoreType>(response);
}

export async function patchStoreType(
  key: string,
  payload: { label?: string; notes?: string; outreach_status?: OutreachStatus },
): Promise<StoreType> {
  const response = await fetch(
    `${API_PROXY_BASE}/b2b/store-types/${encodeURIComponent(key)}`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "PATCH",
    },
  );
  return readJson<StoreType>(response);
}

export async function addStoreTypeCategory(
  key: string,
  categoryPrefix: string[],
): Promise<StoreType> {
  const response = await fetch(
    `${API_PROXY_BASE}/b2b/store-types/${encodeURIComponent(key)}/categories`,
    {
      body: JSON.stringify({ category_prefix: categoryPrefix }),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );
  return readJson<StoreType>(response);
}

export async function removeStoreTypeCategory(
  key: string,
  categoryId: string,
): Promise<StoreType> {
  const response = await fetch(
    `${API_PROXY_BASE}/b2b/store-types/${encodeURIComponent(key)}` +
      `/categories/${encodeURIComponent(categoryId)}`,
    {
      cache: "no-store",
      headers: buildHeaders(true),
      method: "DELETE",
    },
  );
  return readJson<StoreType>(response);
}
