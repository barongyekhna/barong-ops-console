"use client";

import { b2bRequest } from "../api-base";

// 只剩 downloadDocument 在用（下载走裸 fetch，见下）。
const API_PROXY_BASE = "/api/backend";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";
const LABEL = "B2B 单据";

export type BankingField = { key: string; label: string; required: boolean };

export type BankingState = {
  profile: Record<string, string>;
  missing_required: string[];
  fields: BankingField[];
};

export type B2BDocument = {
  id: string;
  number: string;
  doc_type: string;
  doc_type_label: string;
  stage: string;
  stage_label: string;
  status: string;
  issued_on: string;
  valid_until: string;
  buyer_company: string;
  buyer_email: string | null;
  currency: string;
  subtotal: string;
  freight: string | null;
  sample_credit: string | null;
  total: string;
  item_count: number;
  source_document_id: string | null;
};

export const STAGES: { key: string; label: string }[] = [
  { key: "quoted", label: "已报价" },
  { key: "deposit_paid", label: "定金已到" },
  { key: "in_production", label: "生产中" },
  { key: "shipped", label: "已发货" },
  { key: "balance_paid", label: "尾款已到" },
  { key: "closed", label: "已完成" },
];

function buildHeaders() {
  return new Headers({ Accept: "application/json" });
}

export async function getBanking(): Promise<BankingState> {
  return b2bRequest<BankingState>("/b2b/banking", LABEL);
}

export async function saveBanking(
  profile: Record<string, string>,
): Promise<BankingState> {
  return b2bRequest<BankingState>("/b2b/banking", LABEL, {
    body: profile,
    method: "PUT",
  });
}

export async function getDocuments(): Promise<B2BDocument[]> {
  return b2bRequest<B2BDocument[]>("/b2b/documents", LABEL);
}

export async function createDocument(payload: {
  buyer_company: string;
  buyer_contact?: string | null;
  buyer_email?: string | null;
  buyer_address?: string | null;
  ship_to?: string | null;
  lines: { item_id: string; qty: number }[];
  freight?: number | null;
  /** 货代报价（我们的成本）。首单免运费用它算封顶。 */
  freight_quote?: number | null;
  notes?: string | null;
}): Promise<B2BDocument> {
  return b2bRequest<B2BDocument>("/b2b/documents", LABEL, {
    body: payload,
    method: "POST",
  });
}

/** 下载 PDF。走 blob，浏览器直接存盘。 */
export async function downloadDocument(
  documentId: string,
  number: string,
): Promise<void> {
  // 下载保留裸 fetch：要的是 blob 和 Content-Disposition，
  // 而 apiRequest 的契约是「返回解析后的 JSON」。硬塞进去只会让返回类型说谎。
  const response = await fetch(
    `${API_PROXY_BASE}/b2b/documents/${documentId}/pdf`,
    { cache: "no-store", headers: buildHeaders() },
  );
  if (!response.ok) {
    throw new Error(`${LABEL} 下载失败（${response.status}）`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${number}.pdf`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export type SampleCredit = {
  id: string;
  buyer_email: string;
  buyer_company: string | null;
  amount: string;
  currency: string;
  paid_on: string;
  note: string | null;
  consumed: boolean;
};

/** 样品费台账。开 PI 时自动抵扣，不用你记。 */
export async function getSampleCredits(): Promise<SampleCredit[]> {
  return b2bRequest<SampleCredit[]>("/b2b/sample-credits", LABEL);
}

export async function addSampleCredit(payload: {
  buyer_email: string;
  amount: number;
  buyer_company?: string | null;
  note?: string | null;
}): Promise<SampleCredit> {
  return b2bRequest<SampleCredit>("/b2b/sample-credits", LABEL, {
    body: payload,
    method: "POST",
  });
}

/** 从一张 PI 派生商业发票或装箱单（发货报关要）。 */
export async function createShippingDoc(
  documentId: string,
  payload: {
    doc_type: "commercial_invoice" | "packing_list";
    carton_count?: number | null;
    gross_weight_kg?: number | null;
    net_weight_kg?: number | null;
  },
): Promise<B2BDocument> {
  return b2bRequest<B2BDocument>(
    `/b2b/documents/${documentId}/shipping`,
    LABEL,
    { body: payload, method: "POST" },
  );
}

export async function setDocumentStage(
  documentId: string,
  stage: string,
): Promise<B2BDocument> {
  return b2bRequest<B2BDocument>(
    `/b2b/documents/${documentId}/stage`,
    LABEL,
    { body: { stage }, method: "PATCH" },
  );
}
