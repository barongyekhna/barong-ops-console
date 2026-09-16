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
