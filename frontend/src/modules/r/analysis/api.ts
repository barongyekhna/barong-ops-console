"use client";

import { apiRequest } from "@/lib/api";
import type { RaFrameworkStatus } from "@/modules/r/analysis/types";

const RA_API_BASE = "/api/backend/r/analysis";

export function getRaFrameworkStatus() {
  return apiRequest<RaFrameworkStatus>(`${RA_API_BASE}/status`, {
    bypassCache: true,
  });
}

