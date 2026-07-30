"use client";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
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
  status: string;
  issued_on: string;
  valid_until: string;
  buyer_company: string;
  buyer_email: string | null;
  currency: string;
  subtotal: string;
  freight: string | null;
  total: string;
  item_count: number;
};

function buildHeaders(json = false) {
  const headers = new Headers({ Accept: "application/json" });
  if (json) headers.set("Content-Type", "application/json");
  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

async function readJson<T>(response: Response): Promise<T> {
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: string };
      detail = typeof body.detail === "string" ? body.detail : "";
    } catch {
      // 非 JSON 错误体忽略
    }
    throw new Error(detail || `${LABEL}（${response.status}）`);
  }
  return (await response.json()) as T;
}

export async function getBanking(): Promise<BankingState> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/banking`, {
    cache: "no-store",
    headers: buildHeaders(),
  });
  return readJson<BankingState>(response);
}

export async function saveBanking(
  profile: Record<string, string>,
): Promise<BankingState> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/banking`, {
    body: JSON.stringify(profile),
    headers: buildHeaders(true),
    method: "PUT",
  });
  return readJson<BankingState>(response);
}

export async function getDocuments(): Promise<B2BDocument[]> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/documents`, {
    cache: "no-store",
    headers: buildHeaders(),
  });
  return readJson<B2BDocument[]>(response);
}

export async function createDocument(payload: {
  buyer_company: string;
  buyer_contact?: string | null;
  buyer_email?: string | null;
  buyer_address?: string | null;
  ship_to?: string | null;
  lines: { item_id: string; qty: number }[];
  freight?: number | null;
  notes?: string | null;
}): Promise<B2BDocument> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/documents`, {
    body: JSON.stringify(payload),
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<B2BDocument>(response);
}

/** 下载 PDF。走 blob，浏览器直接存盘。 */
export async function downloadDocument(
  documentId: string,
  number: string,
): Promise<void> {
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
