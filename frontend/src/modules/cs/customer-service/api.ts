"use client";

import { apiRequest } from "@/lib/api";

export type CSChannel = "retail" | "wholesale";
export type CSMessageStatus = "new" | "in_progress" | "resolved" | "spam";

export type CSMessage = {
  id: string;
  channel: CSChannel;
  name: string;
  email: string;
  company: string | null;
  order_number: string | null;
  message: string;
  source_url: string | null;
  client_ip: string | null;
  user_agent: string | null;
  status: CSMessageStatus;
  internal_note: string | null;
  created_at: string;
  updated_at: string;
};

export type CSMessageList = {
  items: CSMessage[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

export type CSSummary = {
  retail: { new: number };
  wholesale: { new: number };
};

export type CSMessagePatch = {
  status: CSMessageStatus;
  internal_note: string | null;
};

export const EMPTY_CS_SUMMARY: CSSummary = {
  retail: { new: 0 },
  wholesale: { new: 0 },
};

export async function getCSMessages({
  channel,
  page = 1,
  signal,
  status,
}: {
  channel: CSChannel;
  page?: number;
  signal?: AbortSignal;
  status?: CSMessageStatus;
}): Promise<CSMessageList> {
  const params = new URLSearchParams({
    channel,
    page: String(Math.max(1, Math.floor(page))),
  });
  if (status) {
    params.set("status", status);
  }
  return apiRequest<CSMessageList>(`/cs/messages?${params.toString()}`, {
    bypassCache: true,
    method: "GET",
    signal,
  });
}

export async function getCSMessage(
  messageId: string,
  signal?: AbortSignal,
): Promise<CSMessage> {
  return apiRequest<CSMessage>(
    `/cs/messages/${encodeURIComponent(messageId)}`,
    {
      bypassCache: true,
      method: "GET",
      signal,
    },
  );
}

export async function updateCSMessage(
  messageId: string,
  patch: CSMessagePatch,
): Promise<CSMessage> {
  return apiRequest<CSMessage>(
    `/cs/messages/${encodeURIComponent(messageId)}`,
    {
      body: patch,
      bypassCache: true,
      method: "PATCH",
    },
  );
}

export async function getCSSummary(
  signal?: AbortSignal,
): Promise<CSSummary> {
  return apiRequest<CSSummary>("/cs/summary", {
    bypassCache: true,
    method: "GET",
    signal,
  });
}
