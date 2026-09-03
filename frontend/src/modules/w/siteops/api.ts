"use client";

import { requestWithLabel } from "@/lib/labelled-api";

/**
 * 运单刷新的超时预算。
 *
 * 后端 `TRACK17_TIMEOUT_SECONDS = 15` —— **和 `lib/api.ts` 给非 GET 的默认
 * 超时一模一样**。两边相等意味着前端可能在后端还没用完自己那 15 秒时就掐断，
 * 是必然偶发的失败。留出余量,让后端先超时并给出人话，而不是前端先放弃。
 */
const TRACK_REFRESH_TIMEOUT_MS = 45_000;


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

export type ShippingZoneOption = {
  id: number;
  name: string;
};

export async function getShippingZones(): Promise<ShippingZoneOption[]> {
  return requestWithLabel<ShippingZoneOption[]>(
    "/w/shipping/zones",
    "配送区域",
  );
}

export async function getShippingClasses(): Promise<ShippingClass[]> {
  return requestWithLabel<ShippingClass[]>(
    "/w/shipping/classes",
    "运费模板",
  );
}

export async function createShippingClass(
  payload: ShippingClassCreatePayload,
): Promise<ShippingClass> {
  return requestWithLabel<ShippingClass>(
    "/w/shipping/classes",
    "新增模板",
    { body: payload, method: "POST" },
  );
}

export async function patchShippingClass(
  id: string,
  payload: ShippingClassPatchPayload,
): Promise<ShippingClass> {
  return requestWithLabel<ShippingClass>(
    `/w/shipping/classes/${id}`,
    "保存",
    { body: payload, method: "PATCH" },
  );
}

export async function syncShippingClass(id: string): Promise<unknown> {
  return requestWithLabel<unknown>(
    `/w/shipping/classes/${id}/sync`,
    "同步到 Woo",
    { method: "POST" },
  );
}

export async function deleteShippingClass(
  id: string,
): Promise<{ deleted: boolean; dispatched: boolean }> {
  return requestWithLabel(
    `/w/shipping/classes/${id}`,
    "删除模板",
    { method: "DELETE" },
  );
}

export async function getOrders(
  filter: WOrderFilter = "all",
): Promise<WOrdersResponse> {
  const query = new URLSearchParams({ filter });
  return requestWithLabel<WOrdersResponse>(
    `/w/orders?${query.toString()}`,
    "订单与物流",
  );
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
  return requestWithLabel<ProductSourcesResponse>(
    `/w/sources?${search.toString()}`,
    "货源库",
  );
}

export async function upsertProductSource(
  sku: string,
  payload: ProductSourcePayload,
): Promise<ProductSource> {
  const normalizedSku = normalizeProductSourceSku(sku);
  if (!normalizedSku) throw new Error("SKU 不能为空");
  return requestWithLabel<ProductSource>(
    `/w/sources/${encodeURIComponent(normalizedSku)}`,
    "保存货源",
    { body: payload, method: "PUT" },
  );
}

export async function deleteProductSource(sku: string): Promise<void> {
  const normalizedSku = normalizeProductSourceSku(sku);
  if (!normalizedSku) throw new Error("SKU 不能为空");
  // 后端返 204（无响应体）。`lib/api.ts` 认这个状态并返回 undefined，
  // 所以这里不用再自己判一次 —— 收口前每个 DELETE 都得手写这一行。
  await requestWithLabel<unknown>(
    `/w/sources/${encodeURIComponent(normalizedSku)}`,
    "删除货源",
    { method: "DELETE" },
  );
}

export async function patchOrderTracking(
  id: string,
  payload: { tracking_number: string | null; carrier_code: number | null },
): Promise<TrackingUpdateResponse> {
  return requestWithLabel<TrackingUpdateResponse>(
    `/w/orders/${id}/tracking`,
    "保存运单号",
    { body: payload, method: "PATCH" },
  );
}

export async function refreshOrderTracking(
  id: string,
): Promise<TrackingRefreshResponse> {
  return requestWithLabel<TrackingRefreshResponse>(
    `/w/orders/${id}/refresh-tracking`,
    "刷新轨迹",
    { method: "POST", timeoutMs: TRACK_REFRESH_TIMEOUT_MS },
  );
}

export async function getShippingRules(): Promise<ShippingRule[]> {
  return requestWithLabel<ShippingRule[]>(
    "/w/shipping/rules",
    "分配规则",
  );
}

export async function createShippingRule(
  payload: ShippingRuleCreatePayload,
): Promise<ShippingRule> {
  return requestWithLabel<ShippingRule>(
    "/w/shipping/rules",
    "新增规则",
    { body: payload, method: "POST" },
  );
}

export async function patchShippingRule(
  id: string,
  payload: ShippingRulePatchPayload,
): Promise<ShippingRule> {
  return requestWithLabel<ShippingRule>(
    `/w/shipping/rules/${id}`,
    "保存",
    { body: payload, method: "PATCH" },
  );
}

export async function deleteShippingRule(id: string): Promise<void> {
  await requestWithLabel<unknown>(`/w/shipping/rules/${id}`, "删除", {
    method: "DELETE",
  });
}

export async function simulateShipping(
  payload: ShippingSimulationPayload,
): Promise<ShippingSimulationResult> {
  return requestWithLabel<ShippingSimulationResult>(
    "/w/shipping/simulate",
    "试算",
    { body: payload, method: "POST" },
  );
}

export async function assignShipping(
  productId: string,
  force = false,
): Promise<ShippingAssignResult> {
  return requestWithLabel<ShippingAssignResult>(
    `/w/shipping/assign/${productId}`,
    "重算",
    { body: { force }, method: "POST" },
  );
}

export async function assignAllShipping(): Promise<ShippingAssignAllResult> {
  return requestWithLabel<ShippingAssignAllResult>(
    "/w/shipping/assign-all",
    "重算全部",
    { method: "POST" },
  );
}

export async function getShippingBoard(
  filter: ShippingBoardFilter = "all",
  limit = 500,
): Promise<ShippingBoardResponse> {
  const query = new URLSearchParams({ filter, limit: String(limit) });
  return requestWithLabel<ShippingBoardResponse>(
    `/w/shipping/board?${query.toString()}`,
    "产品台账",
  );
}

export async function patchShippingProduct(
  productId: string,
  payload: ShippingProductPatchPayload,
): Promise<ShippingProductPatchResult> {
  return requestWithLabel<ShippingProductPatchResult>(
    `/w/shipping/products/${productId}`,
    "产品台账",
    { body: payload, method: "PATCH" },
  );
}
