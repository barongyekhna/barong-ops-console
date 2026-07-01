"use client";

import { apiRequest } from "@/lib/api";
import type { ApiKeyType } from "@/modules/keys/key-types";

const API_KEY_ORCHESTRATION_TIMEOUT_MS = 15_000;

export type ApiKeyStatus = "active" | "disabled" | "deleted";
export type ApiKeyRuntimeState = "enabled" | "disabled";

export type ApiKeyRecord = {
  key_id: string;
  org_id: string;
  name: string;
  url: string;
  key_type: ApiKeyType;
  provider: string;
  auth_type: string;
  scope: string[];
  validation_endpoint: string | null;
  key_hash_prefix: string;
  status: ApiKeyStatus;
  runtime_state: ApiKeyRuntimeState;
  assigned_module_ids: string[];
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
};

export type ApiKeyBindingRecord = {
  binding_id: string;
  org_id: string;
  module_id: string;
  key_id: string;
  key_alias: string;
  key_name: string;
  key_url: string;
  key_type: ApiKeyType;
  provider: string;
  status: "active" | "disabled";
  created_at: string;
  updated_at: string;
};

export type ApiKeyListResponse = {
  items: ApiKeyRecord[];
  count: number;
};

export type ApiKeyBindingListResponse = {
  items: ApiKeyBindingRecord[];
  count: number;
};

export function listApiKeys() {
  return apiRequest<ApiKeyListResponse>("/api-key-orchestration/keys", {
    method: "GET",
    timeoutMs: API_KEY_ORCHESTRATION_TIMEOUT_MS,
  });
}

export function createApiKey(payload: {
  org_id: string;
  name: string;
  url: string;
  key_value: string;
  key_type: ApiKeyType;
}) {
  const { org_id: orgId, ...body } = payload;
  return apiRequest<{ item: ApiKeyRecord }>(
    `/api-key-orchestration/organizations/${encodeURIComponent(orgId)}/keys`,
    {
      body,
      method: "POST",
      timeoutMs: API_KEY_ORCHESTRATION_TIMEOUT_MS,
    },
  );
}

export function updateApiKey(
  keyId: string,
  payload: {
    name?: string;
    url?: string;
    key_value?: string;
    key_type?: ApiKeyType;
    status?: ApiKeyStatus;
  },
) {
  return apiRequest<{ item: ApiKeyRecord }>(
    `/api-key-orchestration/keys/${encodeURIComponent(keyId)}`,
    {
      body: payload,
      method: "PATCH",
      timeoutMs: API_KEY_ORCHESTRATION_TIMEOUT_MS,
    },
  );
}

export function deleteApiKey(keyId: string) {
  return apiRequest<{ key_id: string; status: "deleted" }>(
    `/api-key-orchestration/keys/${encodeURIComponent(keyId)}`,
    {
      method: "DELETE",
      timeoutMs: API_KEY_ORCHESTRATION_TIMEOUT_MS,
    },
  );
}

export function listApiKeyBindings() {
  return apiRequest<ApiKeyBindingListResponse>("/api-key-orchestration/bindings", {
    method: "GET",
    timeoutMs: API_KEY_ORCHESTRATION_TIMEOUT_MS,
  });
}

export function createApiKeyBinding(payload: {
  org_id: string;
  module_id: string;
  key_id: string;
  key_alias: string;
}) {
  const { org_id: orgId, ...body } = payload;
  return apiRequest<{ item: ApiKeyBindingRecord }>(
    `/api-key-orchestration/organizations/${encodeURIComponent(orgId)}/bindings`,
    {
      body,
      method: "POST",
      timeoutMs: API_KEY_ORCHESTRATION_TIMEOUT_MS,
    },
  );
}

export function deleteApiKeyBinding(bindingId: string) {
  return apiRequest<{ binding_id: string; status: "disabled" }>(
    `/api-key-orchestration/bindings/${encodeURIComponent(bindingId)}`,
    {
      method: "DELETE",
      timeoutMs: API_KEY_ORCHESTRATION_TIMEOUT_MS,
    },
  );
}
