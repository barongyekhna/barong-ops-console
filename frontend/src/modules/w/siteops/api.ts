"use client";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

export type ShippingOrigin = "cn_direct" | "us_stock";
export type ShippingSyncStatus = "draft" | "pending" | "synced" | "failed";
export type ShippingRuleType =
  | "us_stock_override"
  | "battery_override"
  | "weight_band";
export type ShippingBoardFilter =
  | "all"
  | "unassigned"
  | "review"
  | "exported_missing";

export type ShippingClass = {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  zone_rates_json: ShippingZoneRate[] | null;
  sync_status: ShippingSyncStatus;
  woo_class_id: number | null;
  synced_at: string | null;
  sync_error: string | null;
  origin: ShippingOrigin;
  notes: string | null;
  active: boolean;
  sort_order: number;
  created_at: string | null;
  updated_at: string | null;
};

export type ShippingZoneRate = {
  zone_name: string;
  base_cost: string;
  class_cost: string;
};

export type ShippingRule = {
  id: string;
  priority: number;
  rule_type: ShippingRuleType;
  min_weight_kg: number | null;
  max_weight_kg: number | null;
  shipping_class_slug: string;
  active: boolean;
  notes: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type ShippingAssignment = {
  rule_id: string | null;
  rule_type: ShippingRuleType | "manual" | null;
  matched_at: string | null;
  weight_kg: number | null;
  volumetric_kg: number | null;
  used_kg: number | null;
  review_reason: string | null;
};

export type ShippingBoardSummary = {
  total_dtc: number;
  assigned: number;
  unassigned: number;
  review_needed: number;
  exported_missing: number;
};

export type ShippingBoardItem = {
  product_id: string;
  product_name: string | null;
  sku: string | null;
  channel: "dtc";
  weight_kg: number | null;
  volumetric_kg: number | null;
  used_kg: number | null;
  contains_battery: boolean;
  us_stock: boolean;
  shipping_class_slug: string | null;
  shipping_class_name: string | null;
  assignment: ShippingAssignment | null;
  review_needed: boolean;
  exported: boolean;
};

export type ShippingBoardResponse = {
  summary: ShippingBoardSummary;
  items: ShippingBoardItem[];
};

export type ShippingClassCreatePayload = {
  slug: string;
  name: string;
  description?: string | null;
  zone_rates_json?: ShippingZoneRate[] | null;
  origin: ShippingOrigin;
  notes?: string | null;
  sort_order?: number;
};

export type ShippingClassPatchPayload = {
  name?: string;
  description?: string | null;
  zone_rates_json?: ShippingZoneRate[] | null;
  origin?: ShippingOrigin;
  notes?: string | null;
  active?: boolean;
  sort_order?: number;
};

export type WOrderFilter = "pending" | "tracked" | "all";
export type TrackingStatus =
  | "none"
  | "registered"
  | "info_received"
  | "in_transit"
  | "out_for_delivery"
  | "delivered"
  | "exception"
  | "expired"
  | "not_found";
export type WritebackStatus = "none" | "pending" | "success" | "failed";
export type ProductSourceState = "linked" | "missing";

export type ProductSource = {
  id: string;
  sku: string;
  source_url: string;
  supplier_name: string | null;
  unit_cost: string | number | null;
  currency: string;
  moq: number | null;
  notes: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type ProductSourcePayload = {
  source_url: string;
  supplier_name: string | null;
  unit_cost: number | null;
  currency: string;
  moq: number | null;
  notes: string | null;
};

export type ProductSourcesResponse = {
  items: ProductSource[];
  page: number;
  page_size: number;
  total: number;
  pages?: number;
};

export type WOrderItem = {
  name: string;
  qty: number;
  sku?: string | null;
  source_url?: string | null;
  supplier_name?: string | null;
  unit_cost?: string | number | null;
  currency?: string | null;
  moq?: number | null;
  source_state?: ProductSourceState;
};

export type TrackingEvent = {
  time: string | null;
  location: string | null;
  description: string | null;
};

export type WOrder = {
  id: string;
  woo_order_id: number;
  order_number: string;
  woo_status: string;
  customer_name: string | null;
  country: string | null;
  total: string | number | null;
  currency: string | null;
  items_json: WOrderItem[] | null;
  placed_at: string | null;
  tracking_number: string | null;
  carrier_code: number | null;
  tracking_status: TrackingStatus;
  tracking_events_json: TrackingEvent[] | null;
  tracking_registered: boolean;
  last_tracking_update: string | null;
  writeback_status: WritebackStatus;
  created_at: string | null;
  updated_at: string | null;
};

export type WOrdersResponse = {
  summary: {
    pending: number;
    in_transit: number;
    delivered: number;
    exception: number;
  };
  orders: WOrder[];
};

export type TrackingUpdateResponse = {
  order: WOrder;
  tracking_warning: string | null;
};

export type TrackingRefreshResponse = {
  order: WOrder;
};

export type ShippingRuleCreatePayload = {
  priority: number;
  rule_type: ShippingRuleType;
  min_weight_kg?: number | null;
  max_weight_kg?: number | null;
  shipping_class_slug: string;
  active?: boolean;
  notes?: string | null;
};

export type ShippingRulePatchPayload = {
  priority?: number;
  min_weight_kg?: number | null;
  max_weight_kg?: number | null;
  shipping_class_slug?: string;
  active?: boolean;
  notes?: string | null;
};

export type ShippingSimulationPayload = {
  weight_kg?: number | null;
  volumetric_kg?: number | null;
  contains_battery: boolean;
  us_stock: boolean;
};

export type ShippingSimulationResult = {
  shipping_class_slug: string | null;
  rule_id: string | null;
  rule_type: ShippingRuleType | null;
  weight_kg: number | null;
  volumetric_kg: number | null;
  used_kg: number | null;
  review_needed: boolean;
  review_reason: string | null;
};

export type ShippingAssignResult = Omit<ShippingSimulationResult, "rule_type"> & {
  product_id: string;
  rule_type: ShippingRuleType | "manual" | null;
  skipped_manual: boolean;
  assignment: ShippingAssignment | null;
};

export type ShippingAssignAllResult = {
  assigned: number;
  review_needed: number;
  skipped_manual: number;
  unresolved: number;
};

export type ShippingProductPatchPayload = {
  shipping_class_slug?: string | null;
  contains_battery?: boolean;
  us_stock?: boolean;
  clear_review?: boolean;
};

export type ShippingProductPatchResult = {
  product_id: string;
  shipping_class_slug: string | null;
  contains_battery: boolean;
  us_stock: boolean;
  assignment: ShippingAssignment | null;
  review_needed: boolean;
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

async function readJson<T>(response: Response, label: string): Promise<T> {
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body?.detail ? `：${body.detail}` : "";
    } catch {
      // 忽略非 JSON 错误体
    }
    throw new Error(`${label}（${response.status}）${detail}`);
  }
  return (await response.json()) as T;
}

export type ShippingZoneOption = {
  id: number;
  name: string;
};

export async function getShippingZones(): Promise<ShippingZoneOption[]> {
  const response = await fetch(`${API_PROXY_BASE}/w/shipping/zones`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson<ShippingZoneOption[]>(response, "配送区域");
}

export async function getShippingClasses(): Promise<ShippingClass[]> {
  const response = await fetch(`${API_PROXY_BASE}/w/shipping/classes`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson<ShippingClass[]>(response, "运费模板");
}

export async function createShippingClass(
  payload: ShippingClassCreatePayload,
): Promise<ShippingClass> {
  const response = await fetch(`${API_PROXY_BASE}/w/shipping/classes`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<ShippingClass>(response, "新增模板");
}

export async function patchShippingClass(
  id: string,
  payload: ShippingClassPatchPayload,
): Promise<ShippingClass> {
  const response = await fetch(`${API_PROXY_BASE}/w/shipping/classes/${id}`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "PATCH",
  });
  return readJson<ShippingClass>(response, "保存");
}

export async function syncShippingClass(id: string): Promise<unknown> {
  const response = await fetch(
    `${API_PROXY_BASE}/w/shipping/classes/${id}/sync`,
    {
      cache: "no-store",
      headers: buildHeaders(),
      method: "POST",
    },
  );
  return readJson<unknown>(response, "同步到 Woo");
}

export async function deleteShippingClass(
  id: string,
): Promise<{ deleted: boolean; dispatched: boolean }> {
  const response = await fetch(`${API_PROXY_BASE}/w/shipping/classes/${id}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "DELETE",
  });
  return readJson(response, "删除模板");
}

export async function getOrders(
  filter: WOrderFilter = "all",
): Promise<WOrdersResponse> {
  const query = new URLSearchParams({ filter });
  const response = await fetch(
    `${API_PROXY_BASE}/w/orders?${query.toString()}`,
    { cache: "no-store", headers: buildHeaders(), method: "GET" },
  );
  return readJson<WOrdersResponse>(response, "订单与物流");
}

export function normalizeProductSourceSku(sku: string) {
  return sku.trim().toUpperCase();
}

export function isHttpProductSourceUrl(value: string) {
  try {
    return ["http:", "https:"].includes(new URL(value).protocol);
  } catch {
    return false;
  }
}

export async function getProductSources(
  query = "",
  page = 1,
): Promise<ProductSourcesResponse> {
  const normalizedPage = Number.isInteger(page) && page > 0 ? page : 1;
  const search = new URLSearchParams({
    query: query.trim(),
    page: String(normalizedPage),
  });
  const response = await fetch(
    `${API_PROXY_BASE}/w/sources?${search.toString()}`,
    { cache: "no-store", headers: buildHeaders(), method: "GET" },
  );
  return readJson<ProductSourcesResponse>(response, "货源库");
}

export async function upsertProductSource(
  sku: string,
  payload: ProductSourcePayload,
): Promise<ProductSource> {
  const normalizedSku = normalizeProductSourceSku(sku);
  if (!normalizedSku) throw new Error("SKU 不能为空");
  const response = await fetch(
    `${API_PROXY_BASE}/w/sources/${encodeURIComponent(normalizedSku)}`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "PUT",
    },
  );
  return readJson<ProductSource>(response, "保存货源");
}

export async function deleteProductSource(sku: string): Promise<void> {
  const normalizedSku = normalizeProductSourceSku(sku);
  if (!normalizedSku) throw new Error("SKU 不能为空");
  const response = await fetch(
    `${API_PROXY_BASE}/w/sources/${encodeURIComponent(normalizedSku)}`,
    { cache: "no-store", headers: buildHeaders(), method: "DELETE" },
  );
  if (response.status === 204) return;
  await readJson<unknown>(response, "删除货源");
}

export async function patchOrderTracking(
  id: string,
  payload: { tracking_number: string | null; carrier_code: number | null },
): Promise<TrackingUpdateResponse> {
  const response = await fetch(`${API_PROXY_BASE}/w/orders/${id}/tracking`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "PATCH",
  });
  return readJson<TrackingUpdateResponse>(response, "保存运单号");
}

export async function refreshOrderTracking(
  id: string,
): Promise<TrackingRefreshResponse> {
  const response = await fetch(
    `${API_PROXY_BASE}/w/orders/${id}/refresh-tracking`,
    {
      cache: "no-store",
      headers: buildHeaders(),
      method: "POST",
    },
  );
  return readJson<TrackingRefreshResponse>(response, "刷新轨迹");
}

export async function getShippingRules(): Promise<ShippingRule[]> {
  const response = await fetch(`${API_PROXY_BASE}/w/shipping/rules`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "GET",
  });
  return readJson<ShippingRule[]>(response, "分配规则");
}

export async function createShippingRule(
  payload: ShippingRuleCreatePayload,
): Promise<ShippingRule> {
  const response = await fetch(`${API_PROXY_BASE}/w/shipping/rules`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<ShippingRule>(response, "新增规则");
}

export async function patchShippingRule(
  id: string,
  payload: ShippingRulePatchPayload,
): Promise<ShippingRule> {
  const response = await fetch(`${API_PROXY_BASE}/w/shipping/rules/${id}`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "PATCH",
  });
  return readJson<ShippingRule>(response, "保存");
}

export async function deleteShippingRule(id: string): Promise<void> {
  const response = await fetch(`${API_PROXY_BASE}/w/shipping/rules/${id}`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "DELETE",
  });
  if (response.status === 204) return;
  await readJson<unknown>(response, "删除");
}

export async function simulateShipping(
  payload: ShippingSimulationPayload,
): Promise<ShippingSimulationResult> {
  const response = await fetch(`${API_PROXY_BASE}/w/shipping/simulate`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<ShippingSimulationResult>(response, "试算");
}

export async function assignShipping(
  productId: string,
  force = false,
): Promise<ShippingAssignResult> {
  const response = await fetch(
    `${API_PROXY_BASE}/w/shipping/assign/${productId}`,
    {
      body: JSON.stringify({ force }),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );
  return readJson<ShippingAssignResult>(response, "重算");
}

export async function assignAllShipping(): Promise<ShippingAssignAllResult> {
  const response = await fetch(`${API_PROXY_BASE}/w/shipping/assign-all`, {
    cache: "no-store",
    headers: buildHeaders(),
    method: "POST",
  });
  return readJson<ShippingAssignAllResult>(response, "重算全部");
}

export async function getShippingBoard(
  filter: ShippingBoardFilter = "all",
  limit = 500,
): Promise<ShippingBoardResponse> {
  const query = new URLSearchParams({ filter, limit: String(limit) });
  const response = await fetch(
    `${API_PROXY_BASE}/w/shipping/board?${query.toString()}`,
    { cache: "no-store", headers: buildHeaders(), method: "GET" },
  );
  return readJson<ShippingBoardResponse>(response, "产品台账");
}

export async function patchShippingProduct(
  productId: string,
  payload: ShippingProductPatchPayload,
): Promise<ShippingProductPatchResult> {
  const response = await fetch(
    `${API_PROXY_BASE}/w/shipping/products/${productId}`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "PATCH",
    },
  );
  return readJson<ShippingProductPatchResult>(response, "产品台账");
}
