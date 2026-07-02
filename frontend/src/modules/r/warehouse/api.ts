"use client";

import { apiRequest } from "@/lib/api";
import type {
  RwCategoryTreeResponse,
  RwProductsResponse,
  RwPipelineResponse,
  RwRulesResponse,
  RwRuntimeSettings,
  RwSettingsResponse,
  RwStatus,
} from "@/modules/r/warehouse/types";

const RW_API_BASE = "/api/backend/rw";

export function getRwStatus() {
  return apiRequest<RwStatus>(`${RW_API_BASE}/status`, { bypassCache: true });
}

export function getRwProducts() {
  return getRwProductsWithFilters({});
}

export function getRwProductsWithFilters(filters: {
  q?: string;
  category_id?: string;
  sort_by?: "updated_at" | "skill_score";
  sort_order?: "asc" | "desc";
}) {
  const params = new URLSearchParams();
  if (filters.q) {
    params.set("q", filters.q);
  }
  if (filters.category_id) {
    params.set("category_id", filters.category_id);
  }
  if (filters.sort_by) {
    params.set("sort_by", filters.sort_by);
  }
  if (filters.sort_order) {
    params.set("sort_order", filters.sort_order);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return apiRequest<RwProductsResponse>(`${RW_API_BASE}/products${suffix}`, {
    bypassCache: true,
  });
}

export function getRwRules() {
  return apiRequest<RwRulesResponse>(`${RW_API_BASE}/rules`, {
    bypassCache: true,
  });
}

export function getRwPipeline() {
  return apiRequest<RwPipelineResponse>(`${RW_API_BASE}/pipeline`, {
    bypassCache: true,
  });
}

export function getRwSettings() {
  return apiRequest<RwSettingsResponse>(`${RW_API_BASE}/settings`, {
    bypassCache: true,
  });
}

export function updateRwSettings(settings: Partial<RwRuntimeSettings>) {
  return apiRequest<RwSettingsResponse>(`${RW_API_BASE}/settings`, {
    body: settings,
    method: "POST",
    bypassCache: true,
  });
}

export function getRwCategoryTree() {
  return apiRequest<RwCategoryTreeResponse>(`${RW_API_BASE}/category-tree`, {
    bypassCache: true,
  });
}

export function selectRwCategory(category_id: string, selected: boolean) {
  return apiRequest<RwCategoryTreeResponse>(`${RW_API_BASE}/category-tree/select`, {
    body: { category_id, selected },
    method: "POST",
    bypassCache: true,
  });
}
