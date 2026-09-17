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
  spend_usd?: number;
  sales_usd?: number;
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
  fx_latest?: { date: string; rate: number } | null;
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

// ---- 图片通道(A5):brief / 参考图 / 交稿 / 选定 / 上线。
export type AmzImageGate = { name: string; passed: boolean | null; problems?: string[]; fix?: string[]; skipped?: string; unknown?: string; stands_out?: string; click_rank?: number; must_have_missing?: string[]; forbidden_found?: string[]; text_or_logo?: boolean; notes?: string[]; distances?: { reference_id: string; note: string | null; hamming: number }[] };
export type AmzImageReview = { verdict?: "passed" | "failed" | "unknown"; gates?: AmzImageGate[]; fix?: string[]; reviewed_at?: string; human?: { decision: string; reason: string | null } };
export type AmzImageAsset = { id: string; brief_id: string; kind: string; kind_label: string; round: number; mime_type: string; width: number; height: number; bytes: number; note: string | null; submitted_via: string; status: string; review: AmzImageReview; created_at: string | null };
export type AmzImageBrief = {
  id: string; store_code: string; sku: string | null; asin: string | null; product_line: string; product_line_label: string; position: string; position_label: string; title: string; status: string;
  evidence: Record<string, unknown>; must_have: string[]; forbidden: string[]; rounds: number; max_rounds: number; source_suggestion_id: string | null; chosen_asset_id: string | null;
  live_at: string | null; baseline: Record<string, unknown>; lookback: Record<string, unknown>; created_at: string | null; updated_at: string | null; brief_md?: string;
};
export type AmzImageBriefDetail = { brief: AmzImageBrief; references: AmzImageAsset[]; submissions: AmzImageAsset[]; codex_prompt: string };

export function getImageBriefs(status?: string) {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return amzRequest<{ items: AmzImageBrief[]; positions: Record<string, string>; reference_kinds: Record<string, string> }>(`${BASE}/images/briefs${query}`, "图片 brief 加载失败");
}
export function createImageBrief(payload: { suggestion_id?: string; store_code?: string; position?: string; product_line?: string; sku?: string; asin?: string; title?: string; reason?: string }) {
  return amzRequest<AmzImageBrief>(`${BASE}/images/briefs`, "建 brief 失败", { body: payload, method: "POST" });
}
export function getImageBrief(id: string) {
  return amzRequest<AmzImageBriefDetail>(`${BASE}/images/briefs/${id}`, "brief 加载失败");
}
export function uploadImageReference(id: string, file: File, kind: string, note: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  form.append("note", note);
  return amzRequest<AmzImageAsset>(`${BASE}/images/briefs/${id}/references`, "参考图上传失败", { body: form, method: "POST" });
}
export function uploadImageSubmission(id: string, file: File, note: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("note", note);
  return amzRequest<AmzImageAsset>(`${BASE}/images/briefs/${id}/submit`, "交稿失败", { body: form, method: "POST" });
}
export function decideImageAsset(assetId: string, decision: "choose" | "reject", reason?: string) {
  return amzRequest<AmzImageAsset>(`${BASE}/images/assets/${assetId}/decide`, "选定/驳回失败", { body: { decision, reason: reason ?? null }, method: "POST" });
}
export function markImageBriefLive(id: string, liveOn?: string) {
  return amzRequest<AmzImageBrief>(`${BASE}/images/briefs/${id}/live`, "标记上线失败", { body: { live_on: liveOn ?? null }, method: "POST" });
}
export function imageAssetUrl(assetId: string, kind: "thumbnail" | "preview" | "original" = "preview") {
  return `/api/backend/amz/images/assets/${assetId}/file?kind=${kind}`;
}

// ---- 经验库(A4)。
export type AmzExperienceEntry = { id: string; scope: string; store_code: string | null; action_type: string; action_label: string; kind: string; employee: string | null; statement: string; evidence: Record<string, unknown>; samples: number; hits: number; value: number | null; updated_at: string | null };

export function getExperience(employee?: string) {
  const query = employee ? `?employee=${encodeURIComponent(employee)}` : "";
  return amzRequest<{ items: AmzExperienceEntry[]; params: Record<string, { default: number; cap: number; driven_by: string }> }>(`${BASE}/experience${query}`, "经验库加载失败");
}

// ---- 推新流程与评论簇(A4)。
export type AmzLaunchItem = { key: string; label: string; auto: boolean; ok: boolean; detail: string };
export type AmzReviewCluster = { family: string; family_label: string; owner: string; theme: string; count: number; share_pct: number; sample: string };
export type AmzLaunch = {
  id: string; store_code: string; product_line: string; product_line_label: string; sku: string | null; asin: string | null; title: string; stage: string; stage_label: string;
  inputs: Record<string, unknown>;
  pnl: { ok?: boolean; missing?: string[]; lines?: Record<string, number>; margin_usd?: number; margin_pct?: number | null; floor_usd?: number; breakeven_price_usd?: number | null };
  battlefield: { competitor_asins?: string[]; keywords?: string[]; window_note?: string; pits?: AmzReviewCluster[]; own_clusters?: AmzReviewCluster[] };
  checklist: { items?: AmzLaunchItem[]; all_green?: boolean };
  honeymoon: Record<string, unknown>;
  verdict: { result?: string; missing?: string[]; breaks?: { link: string; why: string; fix: string }[]; judged_on?: string };
  retro: { outcome?: string; lessons?: string[] };
  live_on: string | null; updated_at: string | null;
};

export function getLaunches() {
  return amzRequest<{ items: AmzLaunch[]; stages: Record<string, string>; manual_items: Record<string, string> }>(`${BASE}/launches`, "推新列表加载失败");
}
export function createLaunch(payload: { store_code: string; product_line: string; title: string; sku?: string; asin?: string }) {
  return amzRequest<AmzLaunch>(`${BASE}/launches`, "建推新失败", { body: payload, method: "POST" });
}
export function getLaunch(id: string) {
  return amzRequest<AmzLaunch>(`${BASE}/launches/${id}`, "推新加载失败");
}
export function saveLaunchInputs(id: string, inputs: Record<string, unknown>) {
  return amzRequest<AmzLaunch>(`${BASE}/launches/${id}/inputs`, "保存失败", { body: { inputs }, method: "POST" });
}
export function tickLaunch(id: string, key: string, ok: boolean) {
  return amzRequest<AmzLaunch>(`${BASE}/launches/${id}/tick`, "勾选失败", { body: { key, ok }, method: "POST" });
}
export function advanceLaunch(id: string, overrideReason?: string) {
  return amzRequest<AmzLaunch>(`${BASE}/launches/${id}/advance`, "往下走失败", { body: { override_reason: overrideReason || null }, method: "POST" });
}
export function closeLaunch(id: string, outcome: "growth" | "killed", lessons: string[]) {
  return amzRequest<AmzLaunch>(`${BASE}/launches/${id}/close`, "收尾失败", { body: { outcome, lessons }, method: "POST" });
}
export function pasteReviews(payload: { product_line: string; whose: "ours" | "competitor"; text: string; store_code?: string; asin?: string }) {
  return amzRequest<{ added: number; clustered: { model: number; keywords: number }; clusters: AmzReviewCluster[] }>(`${BASE}/reviews`, "评论入库失败", { body: payload, method: "POST" });
}
export function getReviewClusters(productLine: string, whose?: string) {
  const query = `?product_line=${encodeURIComponent(productLine)}${whose ? `&whose=${whose}` : ""}`;
  return amzRequest<{ clusters: AmzReviewCluster[]; pits: AmzReviewCluster[]; families: Record<string, string> }>(`${BASE}/reviews/clusters${query}`, "评论簇加载失败");
}

// ---- 员工工作日志(硬记忆)。
export type AmzWorkLogEntry = { id: string; kind: string; source: string; 日期: string | null; 店铺: string; 对象: string; 类型: string; 做了什么: string; 为什么: string; 来源: string; 谁: string };

export function getWorkLog(params: { employee: string; store?: string; q?: string }) {
  const query = new URLSearchParams({ employee: params.employee });
  if (params.store) query.set("store", params.store);
  if (params.q) query.set("q", params.q);
  return amzRequest<{ items: AmzWorkLogEntry[]; counts: Record<string, number> }>(`${BASE}/work-log?${query.toString()}`, "工作日志加载失败");
}
