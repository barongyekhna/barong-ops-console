"use client";

// A 系列(亚马逊运营)的接口层。请求统一走 lib/labelled-api → lib/api(/api/backend 代理)。
// 端点形状与 backend/app/modules/amz_series/router.py 一一对应;新加端点要同步登记
// 前端代理白名单 isAllowedAmzPath(漏登记 = 页面红条、后端连日志都没有)。
import { requestWithLabel as amzRequest } from "@/lib/labelled-api";

const BASE = "/amz";

export type AmzStoreAds = {
  spend: number;
  sales: number;
  orders: number;
  acos_pct: number | null;
  first_date: string | null;
  last_date: string | null;
};

export type AmzStoreTransactions = {
  rows: number;
  first_at: string | null;
  last_at: string | null;
};

export type AmzStore = {
  store_code: string;
  display_name: string;
  company_org_id: string;
  company_name: string;
  marketplace_id: string;
  region: string;
  country: string;
  currency: string;
  timezone: string;
  egress_ip: string | null;
  user_agent: string | null;
  status: string;
  role: string;
  ads: AmzStoreAds;
  transactions: AmzStoreTransactions;
};

export type AmzStoresResponse = {
  module_key: string;
  is_owner: boolean;
  items: AmzStore[];
};

export type AmzSeedImport = {
  id: string;
  file_name: string;
  store_code: string;
  kind: string;
  rows: number;
  checksum: string;
  details: Record<string, unknown>;
  imported_at: string | null;
};

export type AmzGrant = {
  user_id: number;
  store_code: string;
  role: string;
  granted_by_user_id: number | null;
  created_at: string | null;
};

export type AmzEmployee = {
  employee: string;
  username: string;
  role_label: string;
  name?: string;
  gender?: string;
  character?: string;
};

export function getStores() {
  return amzRequest<AmzStoresResponse>(`${BASE}/stores`, "店铺清单加载失败");
}

export function getSeedImports() {
  return amzRequest<{ items: AmzSeedImport[] }>(`${BASE}/seed-imports`, "种子导入台账加载失败");
}

export function getEmployees() {
  return amzRequest<{ items: AmzEmployee[] }>(`${BASE}/employees`, "员工名片加载失败");
}

export function getGrants(storeCode: string) {
  return amzRequest<{ items: AmzGrant[] }>(`${BASE}/stores/${storeCode}/grants`, "店铺授权加载失败");
}

export function upsertGrant(storeCode: string, userId: number, role: string) {
  return amzRequest<AmzGrant>(`${BASE}/stores/${storeCode}/grants`, "店铺授权保存失败", {
    body: { user_id: userId, role },
    method: "POST",
  });
}

export function deleteGrant(storeCode: string, userId: number) {
  return amzRequest<{ removed: boolean }>(`${BASE}/stores/${storeCode}/grants/${userId}`, "店铺授权删除失败", {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------- A2:员工消息 / 曲线

export type AmzSuggestion = {
  id: string;
  employee: string;
  employee_label: string;
  employee_name?: string;
  store_code: string;
  action_type: string;
  severity: "bad" | "warn" | "info" | "good" | string;
  title: string;
  why: string;
  prediction: string;
  evidence: Record<string, unknown>;
  level: string;
  status: string;
  reject_reason: string | null;
  decided_by_user_id: number | null;
  decided_at: string | null;
  as_of: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type AmzEmployeePanelItem = {
  employee: string;
  username: string;
  role_label: string;
  name: string;
  gender: string;
  character: string;
  open: number;
  urgent: number;
  latest: AmzSuggestion | null;
};

export type AmzEmployeePanel = {
  items: AmzEmployeePanelItem[];
  open_total: number;
  urgent_total: number;
};

export type AmzSeriesDay = {
  date: string;
  spend_usd: number;
  ad_sales_usd: number;
  ad_orders: number;
  sales_usd: number;
  orders: number;
  tacos_pct: number | null;
};

export type AmzSeries = { days: AmzSeriesDay[]; as_of: string | null; note?: string };

export function getEmployeePanel() {
  return amzRequest<AmzEmployeePanel>(`${BASE}/employees`, "员工面板加载失败");
}

export function getSuggestions(params: { employee?: string; store?: string; status?: string } = {}) {
  const query = new URLSearchParams();
  if (params.employee) query.set("employee", params.employee);
  if (params.store) query.set("store", params.store);
  query.set("status", params.status ?? "open");
  return amzRequest<{ items: AmzSuggestion[]; shadow: boolean }>(`${BASE}/suggestions?${query.toString()}`, "员工消息加载失败");
}

export function decideSuggestion(id: string, decision: "approve" | "reject" | "later", reason?: string) {
  return amzRequest<AmzSuggestion>(`${BASE}/suggestions/${id}/decide`, "记录决定失败", {
    body: { decision, reason: reason ?? null },
    method: "POST",
  });
}

export function getOverviewSeries(params: { store?: string; days?: number } = {}) {
  const query = new URLSearchParams();
  if (params.store) query.set("store", params.store);
  query.set("days", String(params.days ?? 30));
  return amzRequest<AmzSeries>(`${BASE}/overview/series?${query.toString()}`, "曲线加载失败");
}

// ---- 事实表(A2):按产品线手填,AI 判「够不够」。
export type AmzFactSheetUse = "copy" | "image" | "faq" | "pnl";

export type AmzFactSheetFacts = {
  is?: string;
  how_it_works?: string;
  is_not?: string;
  specs?: Record<string, string>;
  indicators?: string;
  package?: string;
  audience?: string;
  misreadings?: string;
  cost?: { factory_cny?: number; freight_cny?: number; price_usd?: number };
  competitor_asins?: string[];
  notes?: string;
};

export type AmzSufficiency = {
  judged_at?: string;
  code?: { uses: Record<string, { label: string; ok: boolean; missing: string[] }>; contradictions: string[]; questions: string[] };
  model?: { contradictions: string[]; questions: string[]; missing_hints: Record<string, string[]> } | null;
  model_error?: string | null;
  ready?: Record<string, boolean>;
};

export type AmzFactSheet = {
  id: string;
  product_line: string;
  product_line_label: string;
  store_code: string | null;
  sku: string | null;
  title: string;
  facts: AmzFactSheetFacts;
  sufficiency: AmzSufficiency;
  version: number;
  status: string;
  updated_by_user_id: number | null;
  updated_at: string | null;
};

export type AmzFactSheetsResponse = { items: AmzFactSheet[]; product_lines: string[]; uses: Record<string, string> };

export function getFactSheets(productLine?: string) {
  const query = productLine ? `?product_line=${encodeURIComponent(productLine)}` : "";
  return amzRequest<AmzFactSheetsResponse>(`${BASE}/fact-sheets${query}`, "事实表加载失败");
}

export function saveFactSheet(payload: { product_line: string; store_code?: string | null; sku?: string | null; title: string; facts: AmzFactSheetFacts }) {
  return amzRequest<AmzFactSheet>(`${BASE}/fact-sheets`, "事实表保存失败", { body: payload, method: "POST" });
}

export function judgeFactSheet(id: string) {
  return amzRequest<AmzFactSheet>(`${BASE}/fact-sheets/${id}/judge`, "事实表核对失败", { method: "POST" });
}

// ---- 广告 API 授权通道(四家公司都走这条)。
export function startAdsOauth(payload: { store_code: string; client_id: string; client_secret: string }) {
  return amzRequest<{ store_code: string; authorize_url: string }>(`${BASE}/ads/oauth/start`, "广告授权启动失败", { body: payload, method: "POST" });
}

export type AdsOauthResult = {
  store_code: string;
  key_id: string;
  alias: string;
  profiles: { profileId: string; countryCode: string; currencyCode: string; timezone: string; accountInfo?: Record<string, unknown> }[];
  all_profiles: number;
};

export function completeAdsOauth(payload: { code: string; state: string }) {
  return amzRequest<AdsOauthResult>(`${BASE}/ads/oauth/callback`, "广告授权收尾失败", { body: payload, method: "POST" });
}
