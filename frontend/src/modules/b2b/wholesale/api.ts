"use client";

// B2B 批发目录的接口层。JSON 请求统一走 `lib/api.ts`。
//
// **一个刻意的例外**:`exportLineSheet` 保留裸 fetch —— 它要的是 blob 和
// Content-Disposition 里的文件名,而 `apiRequest` 的契约是「返回解析后的 JSON」。
// 硬塞进去只会让那个函数的返回类型变成谎话。下载类调用全仓都按这个办法处理。

import { b2bRequest } from "../api-base";

const API_PROXY_BASE = "/api/backend";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";
const LABEL = "B2B 批发目录";
const BASE = "/b2b/wholesale";

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
  /** 这个类目落进哪些店型（对外英文名）。空 = 不会出现在任何批发页上。 */
  store_types: string[];
  /** covered=正常 / blocked=故意不做 / unmapped=缺映射规则 */
  coverage: "covered" | "blocked" | "unmapped";
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

// 只剩 exportLineSheet 在用（下载走裸 fetch，见文件头）。
function buildHeaders() {
  return new Headers({
    Accept: "application/json",
    "Content-Type": "application/json",
  });
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
  return b2bRequest<WholesaleItemList>(`${BASE}/items?${query.toString()}`, LABEL);
}

export async function patchWholesaleItem(
  itemId: string,
  patch: WholesaleItemPatch,
): Promise<WholesaleItem> {
  return b2bRequest<WholesaleItem>(
    `${BASE}/items/${encodeURIComponent(itemId)}`,
    LABEL,
    { body: patch, method: "PATCH" },
  );
}

export async function batchPatchWholesaleItems(
  items: (WholesaleItemPatch & { item_id: string })[],
): Promise<WholesaleItemList> {
  return b2bRequest<WholesaleItemList>(`${BASE}/items`, LABEL, {
    body: { items },
    method: "PATCH",
  });
}

export async function getCategoryReadiness(): Promise<CategoryReadinessList> {
  return b2bRequest<CategoryReadinessList>(`${BASE}/category-readiness`, LABEL);
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
    headers: buildHeaders(),
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
