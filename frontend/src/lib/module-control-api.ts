"use client";

import { apiRequest } from "@/lib/api";

export type ModuleRuntimeStatus = "active" | "error" | "disabled";

export type ModuleControlState = {
  org_id: string;
  module_id: string;
  display_name: string;
  category: string;
  enabled: boolean;
  runtime_status: ModuleRuntimeStatus;
  runtime_error_code: string | null;
  runtime_error_message: string | null;
  last_error_at: string | null;
  updated_at: string;
};

export type ModuleControlOrgGroup = {
  org_id: string;
  org_name: string;
  modules: ModuleControlState[];
};

export type ModuleControlCenterResponse = {
  organizations: ModuleControlOrgGroup[];
  organization_count: number;
  module_count: number;
  auto_registered_count: number;
};

export function listModuleControlCenter() {
  return apiRequest<ModuleControlCenterResponse>("/module-control/center", {
    method: "GET",
    timeoutMs: 45_000,
  });
}

export function updateModuleControlState({
  orgId,
  moduleId,
  enabled,
}: {
  orgId: string;
  moduleId: string;
  enabled: boolean;
}) {
  return apiRequest<{ item: ModuleControlState }>(
    `/module-control/organizations/${encodeURIComponent(
      orgId,
    )}/registry-entries/${encodeURIComponent(moduleId)}`,
    {
      body: { enabled },
      method: "PATCH",
      timeoutMs: 30_000,
    },
  );
}
