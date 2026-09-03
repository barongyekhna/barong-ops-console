"use client";

import { requestWithLabel } from "@/lib/labelled-api";

// 收口时口径从 `${label}（${status}）` 换成 B 式 `${label}（${status}）：${detail}`。
// 是**加信息不是减**：原来后端给的人话被整个丢掉，只剩一个状态码。


export type UploadJob = {
  job_id: string;
  product_id: string;
  product_name: string | null;
  sku: string | null;
  channel: string;
  status: string;
  external_product_id: string | null;
  external_url: string | null;
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
};

export type UploadJobsSummary = {
  total: number;
  success: number;
  failed: number;
  in_flight: number;
};

export type UploadJobsResult = {
  jobs: UploadJob[];
  summary: UploadJobsSummary;
};

export async function getUploadJobs(limit = 50): Promise<UploadJobsResult> {
  return requestWithLabel<UploadJobsResult>(
    `/p/uploads?limit=${limit}`,
    "上架台账加载失败",
  );
}

export type BoardProduct = {
  product_id: string;
  product_name: string | null;
  sku: string | null;
  price: string | null;
  gate_ready: boolean;
  blockers: string[];
  exported: boolean;
  last_job_status: string | null;
  last_external_url: string | null;
};

export type BoardResult = {
  pending: BoardProduct[];
  uploaded: BoardProduct[];
};

export async function getBoard(): Promise<BoardResult> {
  return requestWithLabel<BoardResult>(
    "/p/products/board",
    "产品分组加载失败",
  );
}

export type FaqRecheckResult = {
  status: string; // passed | mismatch | deferred_unpublished | no_upload | audit_failed
  ok: boolean | null;
  page_url: string | null;
  schema_faq_count: number | null;
  visible_faq_present: boolean | null;
  missing_from_visible: unknown[] | null;
  message: string;
};

export async function recheckFaq(productId: string): Promise<FaqRecheckResult> {
  return requestWithLabel<FaqRecheckResult>(
    `/p/products/${productId}/faq-recheck`,
    "FAQ 复检失败",
    { method: "POST" },
  );
}

export async function dispatchProducts(
  productIds: string[],
): Promise<{ queued: string[]; blocked: { product_id: string; blockers: string[] }[] }> {
  return requestWithLabel(
    "/p/dispatch/batch",
    "上传派单失败",
    { body: { product_ids: productIds }, method: "POST" },
  );
}
