"use client";

const API_PROXY_BASE = "/api/backend";
const ACCESS_TOKEN_STORAGE_KEY = "barong_ops_access_token";
const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";
const LABEL = "B2B 开发信";

export type EmailTemplate = {
  id: string;
  kind: string;
  kind_label: string;
  language: string;
  store_type: string;
  subject: string;
  body: string;
  is_builtin: boolean;
  active: boolean;
};

export type EmailDraft = {
  id: string;
  prospect_id: string;
  kind: string;
  language: string;
  to_email: string | null;
  subject: string;
  body: string;
  status: "draft" | "sent" | "skipped";
  store_name: string;
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
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail || `${LABEL}（${response.status}）`);
  }
  return (await response.json()) as T;
}

export async function getTemplates(): Promise<EmailTemplate[]> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/email-templates`, {
    cache: "no-store",
    headers: buildHeaders(),
  });
  return readJson<EmailTemplate[]>(response);
}

export async function seedTemplates(): Promise<{ added: number }> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/email-templates/seed`, {
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<{ added: number }>(response);
}

export async function patchTemplate(
  id: string,
  payload: { subject?: string; body?: string; active?: boolean },
): Promise<EmailTemplate> {
  const response = await fetch(
    `${API_PROXY_BASE}/b2b/email-templates/${encodeURIComponent(id)}`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "PATCH",
    },
  );
  return readJson<EmailTemplate>(response);
}

export async function backfillEmails(payload: {
  limit: number;
  only_fit: boolean;
}): Promise<{ checked: number; found: number; message: string }> {
  const response = await fetch(
    `${API_PROXY_BASE}/b2b/prospect-emails/backfill`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "POST",
    },
  );
  return readJson<{ checked: number; found: number; message: string }>(response);
}

export async function getDrafts(status = "draft"): Promise<EmailDraft[]> {
  const query = new URLSearchParams({ status });
  const response = await fetch(
    `${API_PROXY_BASE}/b2b/email-drafts?${query.toString()}`,
    { cache: "no-store", headers: buildHeaders() },
  );
  return readJson<EmailDraft[]>(response);
}

export async function generateDrafts(payload: {
  kind: string;
  limit: number;
}): Promise<{ created: number; skipped: number; message: string }> {
  const response = await fetch(`${API_PROXY_BASE}/b2b/email-drafts/generate`, {
    body: JSON.stringify(payload),
    cache: "no-store",
    headers: buildHeaders(true),
    method: "POST",
  });
  return readJson<{ created: number; skipped: number; message: string }>(
    response,
  );
}

export async function patchDraft(
  id: string,
  payload: { subject?: string; body?: string; status?: string },
): Promise<EmailDraft> {
  const response = await fetch(
    `${API_PROXY_BASE}/b2b/email-drafts/${encodeURIComponent(id)}`,
    {
      body: JSON.stringify(payload),
      cache: "no-store",
      headers: buildHeaders(true),
      method: "PATCH",
    },
  );
  return readJson<EmailDraft>(response);
}
