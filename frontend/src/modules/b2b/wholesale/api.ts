"use client";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";
const LABEL = "B2B 批发目录";

export type WholesaleStatus = "pending" | "ready" | "archived";

export type PriceTier = {
  min_qty: number;
  unit_price: string;
};

export type WholesaleItem = {
  id: string;
  k_product_id: string | null;
  woo_product_id: number | null;
  sku: string;
  product_name: string;
  category_path: string[];
  image_url: string | null;
  msrp: string | null;
  wholesale_price: string | null;
  price_tiers: PriceTier[];
  case_pack: number | null;
  moq_units: number | null;
  lead_time_days: number | null;
  variant_note: string | null;
  notes: string | null;
  status: WholesaleStatus;
  needs_review: boolean;
  review_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type WholesaleItemList = {
  items: WholesaleItem[];
  count: number;
  pending_count: number;
  ready_count: number;
  needs_review_count: number;
};

export type CategoryReadiness = {
  category_path: string[];
  total_items: number;
  ready_items: number;
  pending_items: number;
  needs_review_items: number;
  prospecting_unlocked: boolean;
  shortfall: number;
};

export type CategoryReadinessList = {
  categories: CategoryReadiness[];
  min_ready_items: number;
};

export type WholesaleItemPatch = {
  wholesale_price?: number;
  case_pack?: number;
  moq_units?: number;
  lead_time_days?: number;
  variant_note?: string;
  notes?: string;
  clear_review_flag?: boolean;
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

async function readError(response: Response): Promise<string> {
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }
  let detail = "";
  try {
    const body = (await response.json()) as { detail?: string };
    detail = typeof body.detail === "string" ? body.detail : "";
  } catch {
    // Ignore non-JSON error bodies.
  }
  return detail || `${LABEL}（${response.status}）`;
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as T;
}

export async function getWholesaleItems(params: {
  status?: WholesaleStatus | "";
  needsReview?: boolean;
  search?: string;
} = {}): Promise<WholesaleItemList> {
  const query = new URLSearchParams();
  if (params.status) {
    query.set("status", params.status);
  }
  if (params.needsReview) {
    query.set("needs_review", "true");
  }
  if (params.search?.trim()) {
    query.set("search", params.search.trim());
  }
  query.set("limit", "500");
  const response = await fetch(
    `${API_PROXY_BASE}/b2b/wholesale/items?${query.toString()}`,
    { cache: "no-store", headers: buildHeaders() },
  );
  return readJson<WholesaleItemList>(response);
}

export async function patchWholesaleItem(
  itemId: string,
  patch: WholesaleItemPatch,
): Promise<WholesaleItem> {
  const response = await fetch(
    `${API_PROXY_BASE}/b2b/wholesale/items/${encodeURIComponent(itemId)}`,
    {
      body: JSON.stringify(patch),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "PATCH",
    },
  );
  return readJson<WholesaleItem>(response);
}

export async function batchPatchWholesaleItems(
  items: (WholesaleItemPatch & { item_id: string })[],
): Promise<WholesaleItemList> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/wholesale/items`, {
    body: JSON.stringify({ items }),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "PATCH",
  });
  return readJson<WholesaleItemList>(response);
}

export async function getCategoryReadiness(): Promise<CategoryReadinessList> {
  const response = await fetch(
    `${API_PROXY_BASE}/b2b/wholesale/category-readiness`,
    { cache: "no-store", headers: buildHeaders() },
  );
  return readJson<CategoryReadinessList>(response);
}

/** 导出图册。返回 blob 让浏览器直接下载,不走 JSON。 */
export async function exportLineSheet(payload: {
  fmt: "pdf" | "csv";
  /** 首选按店型出：一个店型可横跨多个类目，图册一本给全。 */
  store_type?: string | null;
  category_prefix?: string[] | null;
  item_ids?: string[] | null;
  edition_label?: string;
}): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/wholesale/line-sheet`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  return {
    blob: await response.blob(),
    filename: match?.[1] ?? `barong-yekhna-line-sheet.${payload.fmt}`,
  };
}
