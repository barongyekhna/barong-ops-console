"use client";

import { b2bRequest } from "../api-base";

/**
 * 补邮箱和生成草稿都是**同步**的：backfill 逐家抓官网联系页,
 * generate 逐条跑 AI 写稿,耗时随 limit 线性增长。默认 15 秒不够。
 */
const SLOW_BATCH_TIMEOUT_MS = 300_000;

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

export async function getTemplates(): Promise<EmailTemplate[]> {
    return b2bRequest<EmailTemplate[]>("/b2b/email-templates", LABEL);
}

export async function seedTemplates(): Promise<{ added: number }> {
    return b2bRequest<{ added: number }>("/b2b/email-templates/seed", LABEL, { method: "POST" });
}

export async function patchTemplate(
  id: string,
  payload: { subject?: string; body?: string; active?: boolean },
): Promise<EmailTemplate> {
    return b2bRequest<EmailTemplate>(
      `/b2b/email-templates/${encodeURIComponent(id)}`,
      LABEL,
      { body: payload, method: "PATCH" },
    );
}

export async function backfillEmails(payload: {
  limit: number;
  only_fit: boolean;
}): Promise<{ checked: number; found: number; message: string }> {
  return b2bRequest<{ checked: number; found: number; message: string }>(
    "/b2b/prospect-emails/backfill",
    LABEL,
    { body: payload, method: "POST", timeoutMs: SLOW_BATCH_TIMEOUT_MS },
  );
}

export async function getDrafts(status = "draft"): Promise<EmailDraft[]> {
  const query = new URLSearchParams({ status });
    return b2bRequest<EmailDraft[]>(`/b2b/email-drafts?${query.toString()}`, LABEL);
}

export async function generateDrafts(payload: {
  kind: string;
  limit: number;
}): Promise<{ created: number; skipped: number; message: string }> {
  return b2bRequest<{ created: number; skipped: number; message: string }>(
    "/b2b/email-drafts/generate",
    LABEL,
    { body: payload, method: "POST", timeoutMs: SLOW_BATCH_TIMEOUT_MS },
  );
}

export async function patchDraft(
  id: string,
  payload: { subject?: string; body?: string; status?: string },
): Promise<EmailDraft> {
    return b2bRequest<EmailDraft>(
      `/b2b/email-drafts/${encodeURIComponent(id)}`,
      LABEL,
      { body: payload, method: "PATCH" },
    );
}

export type Suppression = {
  id: string;
  email: string;
  raw_email: string | null;
  source: string;
  note: string | null;
};

/** 「永不再发」名单。说过别发了的人，系统里再也生成不出给他的草稿。 */
export async function getSuppressions(): Promise<Suppression[]> {
    return b2bRequest<Suppression[]>("/b2b/suppressions", LABEL);
}

export async function addSuppression(payload: {
  email: string;
  source?: string;
  note?: string;
}): Promise<Suppression> {
    return b2bRequest<Suppression>("/b2b/suppressions", LABEL, { body: payload, method: "POST" });
}
