"use client";

import { apiRequest } from "@/lib/api";
import type {
  RaFrameworkStatus,
  RaAutoProfitPayload,
  RaAutoProfitResult,
  RaManualProfitPayload,
  RaProfitRunResult,
  RaProfitSnapshot,
  RaProfitSnapshotList,
  RaSupplierSearchPayload,
  RaSupplierSearchResult,
} from "@/modules/r/analysis/types";

const RA_API_BASE = "/api/backend/r/analysis";

export function getRaFrameworkStatus() {
  return apiRequest<RaFrameworkStatus>(`${RA_API_BASE}/status`, {
    bypassCache: true,
  });
}

export function getRaProfitSnapshots() {
  return apiRequest<RaProfitSnapshotList>(`${RA_API_BASE}/profit/snapshots`, {
    bypassCache: true,
  });
}

export function calculateManualRaProfit(payload: RaManualProfitPayload) {
  return apiRequest<RaProfitSnapshot>(`${RA_API_BASE}/profit/manual`, {
    body: payload,
    method: "POST",
    timeoutMs: 30_000,
  });
}

export function runRaProfitForExistingOffers(limit = 50) {
  return apiRequest<RaProfitRunResult>(`${RA_API_BASE}/profit/run`, {
    body: { limit },
    method: "POST",
    timeoutMs: 60_000,
  });
}

export function searchRaSuppliers(payload: RaSupplierSearchPayload) {
  return apiRequest<RaSupplierSearchResult>(`${RA_API_BASE}/supplier-search`, {
    body: payload,
    method: "POST",
    timeoutMs: 90_000,
  });
}

export function runRaAutoProfit(payload: RaAutoProfitPayload) {
  return apiRequest<RaAutoProfitResult>(`${RA_API_BASE}/profit/auto-run`, {
    body: payload,
    method: "POST",
    timeoutMs: 180_000,
  });
}
