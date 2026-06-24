"use client";

import { apiRequest } from "@/lib/api";

export const N8N_WEBHOOK_TEST_MODULE_ID =
  "integration.n8n_webhook_test_bridge";

export type N8nWebhookInjectedKey = {
  key_alias: string;
  key_id: string;
  key_name: string;
  header_name: string;
  injected: true;
};

export type N8nWebhookTestRunResponse = {
  run_id: string;
  module_id: typeof N8N_WEBHOOK_TEST_MODULE_ID;
  org_id: string;
  request_sent: boolean;
  n8n_received: boolean;
  response_returned: boolean;
  logs_stored: boolean;
  success: boolean;
  status_code: number | null;
  duration_ms: number;
  operation_log_id: string | null;
  injected_key: N8nWebhookInjectedKey;
  response_body: unknown;
  error_code: string | null;
  error_message: string | null;
};

export function runN8nWebhookTest(payload: {
  org_id: string;
  key_alias?: string;
  correlation_id?: string;
  payload?: Record<string, unknown>;
}) {
  return apiRequest<N8nWebhookTestRunResponse>("/n8n-webhook-test/run", {
    body: {
      key_alias: payload.key_alias || "n8n",
      org_id: payload.org_id,
      correlation_id: payload.correlation_id,
      payload: payload.payload ?? {},
    },
    method: "POST",
    timeoutMs: 30_000,
  });
}
