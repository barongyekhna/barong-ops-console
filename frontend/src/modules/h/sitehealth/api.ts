"use client";

import { requestPreferDetail } from "@/lib/labelled-api";

export type HealthRunTrigger = "scheduled" | "manual";
export type HealthRunStatus = "running" | "completed" | "failed";
export type HealthFindingType =
  | "broken_link"
  | "slow_page"
  | "sitemap_error"
  | "homepage_error";
export type HealthFindingStatus = "open" | "acknowledged" | "resolved";
export type HealthFindingAction = "acknowledge" | "resolve" | "reopen";

export type HealthRun = {
  id: string;
  trigger: HealthRunTrigger;
  status: HealthRunStatus;
  started_at: string | null;
  finished_at: string | null;
  urls_total: number;
  urls_ok: number;
  urls_broken: number;
  urls_slow: number;
  avg_response_ms: number | null;
  p95_response_ms: number | null;
  sitemap_ok: boolean;
  homepage_ok: boolean;
  summary_json: Record<string, unknown> | null;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type HealthFinding = {
  id: string;
  run_id: string;
  finding_type: HealthFindingType;
  url: string;
  status_code: number | null;
  response_ms: number | null;
  detail: string | null;
  status: HealthFindingStatus;
  created_at: string | null;
  updated_at: string | null;
};

export type HealthRunDetail = HealthRun & {
  findings: HealthFinding[];
};

export type RedirectRule = {
  from: string;
  to: string;
};

export type RedirectsResponse = {
  reachable: boolean;
  rules: RedirectRule[];
  parse_error?: string;
  error?: string;
};

export type RedirectVerification = {
  reachable?: boolean;
  status: number | null;
  location: string | null;
  error?: string;
};

export type WpPlugin = {
  plugin: string;
  name: string;
  status: string;
  version: string;
};

export type WpPing = {
  slug: string;
  ok: boolean;
  version: string;
};

export type WpMailItem = {
  time: string;
  to: string;
  subject: string;
};

export type WpSentinel = {
  reachable: boolean;
  plugins: WpPlugin[];
  pings: WpPing[];
  mail: {
    items: WpMailItem[];
    recent_failures: number;
  };
  error?: string;
};

export type SmtpDiagnostic = {
  reachable: boolean;
  probe?: string | null;
  verdict_line?: string | null;
  host?: string | null;
  username?: string | null;
  error?: string;
};

export async function getHealthRuns(
  limit = 30,
): Promise<{ runs: HealthRun[] }> {
  return requestPreferDetail<{ runs: HealthRun[] }>(
    `/h/runs?limit=${limit}`,
    "H 站点健康",
  );
}

export async function getHealthRun(runId: string): Promise<HealthRunDetail> {
  return requestPreferDetail<HealthRunDetail>(
    `/h/runs/${encodeURIComponent(runId)}`,
    "H 站点健康",
  );
}

export async function triggerHealthRun(): Promise<HealthRun> {
  // 往 n8n 派单，不是当场跑体检 —— 默认超时够用。
  return requestPreferDetail<HealthRun>("/h/runs/trigger", "H 站点健康", {
    method: "POST",
  });
}

export async function getHealthFindings(params: {
  status: HealthFindingStatus;
  findingType?: HealthFindingType;
  limit?: number;
}): Promise<{ items: HealthFinding[]; total: number }> {
  const query = new URLSearchParams({
    limit: String(params.limit ?? 100),
    status: params.status,
  });
  if (params.findingType) {
    query.set("finding_type", params.findingType);
  }
  return requestPreferDetail<{ items: HealthFinding[]; total: number }>(
    `/h/findings?${query.toString()}`,
    "H 站点健康",
  );
}

export async function updateHealthFinding(
  findingId: string,
  action: HealthFindingAction,
): Promise<HealthFinding> {
  return requestPreferDetail<HealthFinding>(
    `/h/findings/${encodeURIComponent(findingId)}`,
    "H 站点健康",
    { body: { action }, method: "PATCH" },
  );
}

export async function getWpRedirects(): Promise<RedirectsResponse> {
  return requestPreferDetail<RedirectsResponse>("/h/wp/redirects", "跳转管理");
}

export async function saveWpRedirects(
  rules: RedirectRule[],
): Promise<RedirectsResponse> {
  return requestPreferDetail<RedirectsResponse>(
    "/h/wp/redirects",
    "保存跳转规则",
    { body: { rules }, method: "PUT" },
  );
}

export async function verifyWpRedirect(
  path: string,
): Promise<RedirectVerification> {
  return requestPreferDetail<RedirectVerification>(
    "/h/wp/redirects/verify",
    "验证跳转规则",
    { body: { path }, method: "POST" },
  );
}

export async function getWpSentinel(): Promise<WpSentinel> {
  return requestPreferDetail<WpSentinel>("/h/wp/sentinel", "插件哨兵");
}

export async function runWpSmtpCheck(): Promise<SmtpDiagnostic> {
  // 后端对 WP 的调用统一 WP_TIMEOUT_SECONDS=10，所以 15 秒默认够用。
  return requestPreferDetail<SmtpDiagnostic>("/h/wp/smtp-check", "SMTP 体检", {
    method: "POST",
  });
}
