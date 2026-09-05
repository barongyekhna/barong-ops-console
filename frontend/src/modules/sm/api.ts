"use client";

// SM 系列（社媒运营）的接口层。请求统一走 lib/labelled-api → lib/api（/api/backend 代理）。
// 端点形状与 backend/app/modules/sm_series/router.py 一一对应；新加端点要同步登记
// 前端代理白名单 isAllowedSmPath（漏登记 = 页面红条、后端连日志都没有）。

import { requestWithLabel as smRequest } from "@/lib/labelled-api";

const BASE = "/sm";
const API_PROXY_BASE = "/api/backend";

export type Platform = "pinterest" | "instagram" | "facebook";
export type Pillar = "P1" | "P2" | "P3" | "P4" | "P5";

export type PlatformProfile = {
  platform: Platform;
  voice: string;
  pillar_mix: Record<string, number>;
  weekly_template: Record<string, string>;
  per_day: number[];
  windows_pt: string[];
  formats: string[];
  image: { ratio: string; min_px: number[]; overlay_max_area: number };
  fields: { title: number; title_visible: number; caption: number; first_line: number; alt: number };
  hashtags: { max: number };
  link: { mode: string; utm: boolean };
  cooldown_days_same_source: number;
  phase_rules: { seeding_days: number };
  skill_section: string;
  version: string;
  notes: string;
};

export type ImageRequirement = {
  pillar: Pillar;
  platform: Platform;
  roles: string[];
  ratio: string;
  count_min: number;
  count_max: number;
  overlay: boolean;
  must_be_real: boolean;
  text_card_ok: boolean;
  post_kind: string;
};

export type ProfilesResponse = {
  version: string;
  profiles: PlatformProfile[];
  image_requirements: ImageRequirement[];
  pillars: { key: Pillar; label: string }[];
  reject_reasons: { code: string; label: string }[];
};

export type Channel = {
  id: string;
  platform: Platform;
  handle: string | null;
  mode: string;
  status: string;
  profile_version: string;
  notes: string | null;
  created_at: string | null;
};

export type InventorySummary = {
  products: number;
  products_in_stock: number;
  guides: number;
  facts: number;
  factory_photos: number;
  brand_assets: number;
  pin_reserve_estimate: number;
};

export type Inventory = {
  summary: InventorySummary;
  products: {
    product_id: string;
    sku: string;
    name: string;
    public_url: string;
    in_stock: boolean;
    brand_clean: boolean;
    asset_counts: Record<string, number>;
    last_posted: Record<string, string | null>;
  }[];
  guides: {
    item_id: string;
    title: string;
    item_type: string;
    public_url: string;
    seed_product_id: string | null;
    section_count: number;
    last_posted: Record<string, string | null>;
  }[];
  facts: { fact_id: string; topic: string; claim: string }[];
};

export type MediaRef = {
  slot: number | null;
  asset_id: string | null;
  layout_asset_id: string | null;
  overlay_text: string | null;
  kind: string | null;
  thumbnail_url: string | null;
};

export type PostSummary = {
  id: string;
  platform: Platform;
  post_kind: string;
  post_kind_label: string;
  pillar: Pillar;
  title: string;
  first_line: string | null;
  review_status: string;
  generation_status: string;
  publish_status: string;
  audit_clean: boolean | null;
  audit_unresolved: number | null;
  media: MediaRef[];
  permalink: string | null;
  updated_at: string | null;
};

export type PostDetail = PostSummary & {
  slot_id: string | null;
  source_type: string;
  source_id: string | null;
  seed_product_id: string | null;
  caption: string | null;
  alt_text: string | null;
  hashtags: string[];
  board: string | null;
  link_url: string | null;
  keyword_primary: string | null;
  keywords_secondary: string[];
  cta: string | null;
  facts_used: string[];
  brand_audit: Record<string, unknown> | null;
  analysis: Record<string, unknown> | null;
  revision: Record<string, unknown> | null;
  skill_version: string | null;
  provider: string | null;
  external_id: string | null;
  posted_at: string | null;
  created_at: string | null;
  reject_reasons: { code: string; label: string }[];
  candidates: { asset_id: string; asset_role: string; thumbnail_url: string | null }[];
};

export type Gap = {
  id: string;
  slot_id: string | null;
  source_type: string;
  source_id: string | null;
  seed_product_id: string | null;
  pillar: Pillar;
  pillar_label: string;
  platform: Platform;
  role: string;
  count: number;
  ratio: string;
  lane: "layout" | "mcp" | "photo";
  k_position: number | null;
  due_day: string;
  status: string;
  brief_text: string | null;
  prompt_text: string | null;
  filled_asset_id: string | null;
  created_at: string | null;
};

export type Slot = {
  id: string;
  day: string;
  weekday: number;
  platform: Platform;
  slot_index: number;
  window_pt: string | null;
  pillar: Pillar;
  pillar_label: string;
  label: string;
  source_type: string;
  source_id: string | null;
  seed_product_id: string | null;
  seed_product_sku: string | null;
  status: string;
  swap_reason: string | null;
  post_kind: string | null;
  media_plan: {
    asset_ids: string[];
    thumbnail_urls: (string | null)[];
    needs_layout: boolean;
    text_card: boolean;
    mirror_of_slot: string | null;
    gap: Record<string, unknown> | null;
  };
  gap: Gap | null;
  post: PostSummary | null;
  planner_version: string;
};

export type Calendar = { from: string; to: string; platforms: Platform[]; slots: Slot[] };

export type Job = {
  job_id: string;
  slot_id: string | null;
  post_id: string | null;
  job_type: string;
  status: string;
  attempts: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
};

export type PlanResult = {
  run_id: string;
  created: number;
  blocked: number;
  per_platform: Record<string, number>;
  start_day: string;
  days: number;
};

/** 后端给的是裸 /k/media/... 路径，浏览器要加代理前缀，否则图全是裂的。 */
export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  return path.startsWith("/api/") ? path : `${API_PROXY_BASE}${path}`;
}

export function getProfiles() {
  return smRequest<ProfilesResponse>(`${BASE}/profiles`, "渠道档案加载失败");
}

export function getChannels() {
  return smRequest<{ channels: Channel[] }>(`${BASE}/channels`, "渠道加载失败");
}

export function createChannel(payload: { platform: Platform; handle?: string | null; notes?: string | null }) {
  return smRequest<Channel>(`${BASE}/channels`, "登记渠道失败", { body: payload, method: "POST" });
}

export function patchChannel(id: string, payload: { handle?: string | null; status?: "active" | "paused"; notes?: string | null }) {
  return smRequest<Channel>(`${BASE}/channels/${id}`, "更新渠道失败", { body: payload, method: "PATCH" });
}

export function getInventory() {
  return smRequest<Inventory>(`${BASE}/inventory`, "库存盘点加载失败");
}

export function planCalendar(days = 28) {
  return smRequest<PlanResult>(`${BASE}/calendar/plan`, "排期失败", { body: { days }, method: "POST", timeoutMs: 60_000 });
}

export function getCalendar(from: string, to: string, platform?: Platform) {
  const params = new URLSearchParams({ from, to });
  if (platform) params.set("platform", platform);
  return smRequest<Calendar>(`${BASE}/calendar?${params.toString()}`, "日历加载失败");
}

export function writeSlot(slotId: string) {
  return smRequest<{ job_id: string; slot_id: string; status: string }>(`${BASE}/slots/${slotId}/write`, "入队失败", {
    body: {},
    method: "POST",
  });
}

export function swapSlot(slotId: string, payload: { pillar?: Pillar; reason?: string }) {
  return smRequest<Slot>(`${BASE}/slots/${slotId}/swap`, "换支柱失败", { body: payload, method: "POST" });
}

export function getPosts(params: { review_status?: string; platform?: Platform } = {}) {
  const search = new URLSearchParams();
  if (params.review_status) search.set("review_status", params.review_status);
  if (params.platform) search.set("platform", params.platform);
  const query = search.toString();
  return smRequest<{ posts: PostSummary[] }>(`${BASE}/posts${query ? `?${query}` : ""}`, "帖子列表加载失败");
}

export function getPost(id: string) {
  return smRequest<PostDetail>(`${BASE}/posts/${id}`, "帖子加载失败");
}

export function rejectImage(postId: string, payload: { asset_id: string; reason_code: string; replacement_asset_id?: string | null; note?: string | null }) {
  return smRequest<PostDetail>(`${BASE}/posts/${postId}/reject-image`, "驳回图片失败", { body: payload, method: "POST" });
}

export function pickImage(postId: string, payload: { asset_id: string; slot_index: number }) {
  return smRequest<PostDetail>(`${BASE}/posts/${postId}/pick-image`, "指定图片失败", { body: payload, method: "POST" });
}

export function markPosted(postId: string, payload: { permalink: string; external_id?: string | null }) {
  return smRequest<PostDetail>(`${BASE}/posts/${postId}/mark-posted`, "标记已发布失败", { body: payload, method: "POST" });
}

export function getImageRequests(params: { lane?: string; status?: string } = {}) {
  const search = new URLSearchParams();
  if (params.lane) search.set("lane", params.lane);
  if (params.status) search.set("status", params.status);
  const query = search.toString();
  return smRequest<{ requests: Gap[] }>(`${BASE}/image-requests${query ? `?${query}` : ""}`, "缺口单加载失败");
}

export function dismissImageRequest(id: string) {
  return smRequest<Gap>(`${BASE}/image-requests/${id}/dismiss`, "关闭缺口单失败", { body: {}, method: "POST" });
}

export function getJobs() {
  return smRequest<{ jobs: Job[] }>(`${BASE}/jobs`, "任务列表加载失败");
}

/** 点「唤起 Codex 作图」预填进 Codex 的指令（与 K 那颗按钮同一写法：先复制到剪贴板，再 deep link）。 */
export function codexPromptForGap(sku: string, position: number | null): string {
  const pos = position ? `第 ${position} 位` : "社媒位（201 起）";
  return (
    `用 barong_k_images:先 k_get_image_brief 取 ${sku} 的简报,再 k_get_reference_images ` +
    `取全部参考图并下载到本地。只出简报里的 ${pos}（社媒场景图）,产品像素以参考图为准不许改结构,` +
    "严格遵守简报里的工作原理与配件清单。出完先对照参考图自查,再 k_submit_image 交上去;" +
    "交完等 2 分钟用 k_get_submission_status 看审查,被打回就按报告改了重交。最后汇报状态。"
  );
}

export const PLATFORM_LABEL: Record<Platform, string> = {
  pinterest: "Pinterest",
  instagram: "Instagram",
  facebook: "Facebook",
};

export const PILLAR_LABEL: Record<Pillar, string> = {
  P1: "产品",
  P2: "导购",
  P3: "工厂",
  P4: "场景",
  P5: "品牌",
};

export const WEEKDAY_LABEL = ["一", "二", "三", "四", "五", "六", "日"];
