import { apiRequest } from "@/lib/api";

export type WebhookRegistryEntry = {
  id: number;
  series: string;
  workflow_name: string;
  webhook_url: string;
  respond_url: string | null;
  notes: string | null;
};

export function listWebhookRegistry() {
  return apiRequest<{ entries: WebhookRegistryEntry[] }>("/webhook-registry", {
    bypassCache: true,
  });
}

export function createWebhookRegistryEntry(payload: {
  series: string;
  workflow_name: string;
  webhook_url: string;
  respond_url?: string;
  notes?: string;
}) {
  return apiRequest<WebhookRegistryEntry>("/webhook-registry", {
    body: payload,
    method: "POST",
  });
}

export function deleteWebhookRegistryEntry(id: number) {
  return apiRequest<void>(`/webhook-registry/${id}`, { method: "DELETE" });
}
