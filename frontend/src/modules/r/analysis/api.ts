"use client";

import { apiRequest } from "@/lib/api";
import type {
  RaFrameworkStatus,
  RaAutoProfitPayload,
  RaAutoProfitJobPayload,
  RaAutoProfitJobItemsQuery,
  RaAutoProfitJobResult,
  RaAutoProfitResult,
  RaExpansion,
  RaGroupsPayload,
  RaGroupItem,
  RaJobStatusResult,
  RaKImportResult,
  RaOpusReview,
  RaReportDetail,
  RaManualProfitPayload,
  RaProfitRunResult,
  RaProfitSnapshot,
  RaProfitSnapshotList,
  RaQuotaPayload,
  RaRunEventsPayload,
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

export function createRaAutoProfitJob(payload: RaAutoProfitJobPayload) {
  return apiRequest<RaAutoProfitJobResult>(`${RA_API_BASE}/profit/jobs`, {
    body: payload,
    method: "POST",
    timeoutMs: 30_000,
  });
}

export function getRaAutoProfitJob(runId: string, query?: RaAutoProfitJobItemsQuery) {
  const searchParams = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    searchParams.set(key, String(value));
  });
  const suffix = searchParams.size ? `?${searchParams.toString()}` : "";
  return apiRequest<RaAutoProfitJobResult>(`${RA_API_BASE}/profit/jobs/${runId}${suffix}`, {
    bypassCache: true,
    timeoutMs: 60_000,
  });
}

export function getRaJobStatus(runId: string = "latest") {
  return apiRequest<RaJobStatusResult>(`${RA_API_BASE}/runs/${runId}/status`, {
    bypassCache: true,
    timeoutMs: 20_000,
  });
}

export function getRaRunEvents(
  runId: string = "latest",
  after = 0,
  limit = 200,
) {
  return apiRequest<RaRunEventsPayload>(
    `${RA_API_BASE}/runs/${runId}/events?after=${after}&limit=${limit}`,
    { bypassCache: true, timeoutMs: 20_000 },
  );
}

export function getRaGroups(channel?: string) {
  const suffix = channel ? `?channel=${encodeURIComponent(channel)}` : "";
  return apiRequest<RaGroupsPayload>(`${RA_API_BASE}/groups${suffix}`, {
    bypassCache: true,
    timeoutMs: 30_000,
  });
}

export function getRaQuota() {
  return apiRequest<RaQuotaPayload>(`${RA_API_BASE}/quota`, {
    bypassCache: true,
    timeoutMs: 20_000,
  });
}

export function approveRaReport(reportId: string) {
  return apiRequest<RaGroupItem>(`${RA_API_BASE}/reports/${reportId}/approve`, {
    method: "POST",
    timeoutMs: 20_000,
  });
}

export function rejectRaReport(reportId: string) {
  return apiRequest<RaGroupItem>(`${RA_API_BASE}/reports/${reportId}/reject`, {
    method: "POST",
    timeoutMs: 20_000,
  });
}

export function getRaReportDetail(reportId: string) {
  return apiRequest<RaReportDetail>(`${RA_API_BASE}/reports/${reportId}/detail`, {
    bypassCache: true,
    timeoutMs: 30_000,
  });
}

export function requestRaOpusReview(reportId: string) {
  return apiRequest<RaOpusReview>(`${RA_API_BASE}/reports/${reportId}/opus-review`, {
    method: "POST",
    timeoutMs: 150_000,
  });
}

export function createRaExpansion(reportId: string) {
  return apiRequest<RaExpansion>(`${RA_API_BASE}/reports/${reportId}/expand`, {
    method: "POST",
    timeoutMs: 30_000,
  });
}

export function getRaExpansion(reportId: string) {
  return apiRequest<RaExpansion>(`${RA_API_BASE}/reports/${reportId}/expansion`, {
    bypassCache: true,
    timeoutMs: 30_000,
  });
}

export function importRaProductsToK(asins: string[], channel: "amazon" | "dtc") {
  return apiRequest<RaKImportResult>("/api/backend/k/products/import-from-r", {
    body: { asins, channel },
    method: "POST",
    timeoutMs: 60_000,
  });
}

export function getLatestRaAutoProfitJob(query?: RaAutoProfitJobItemsQuery) {
  const searchParams = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    searchParams.set(key, String(value));
  });
  const suffix = searchParams.size ? `?${searchParams.toString()}` : "";
  return apiRequest<RaAutoProfitJobResult>(`${RA_API_BASE}/profit/jobs/latest${suffix}`, {
    bypassCache: true,
    timeoutMs: 60_000,
  });
}

export type RaCruiseState = {
  paused: boolean;
  updated_at: string | null;
  updated_by: string | null;
  today: {
    ai_evaluations: number;
    providers: { provider: string; label: string; used: number }[];
  };
};

export async function getCruiseState(): Promise<RaCruiseState> {
  return apiRequest<RaCruiseState>(`${RA_API_BASE}/cruise`, {
    method: "GET",
  });
}

export async function toggleCruise(paused: boolean): Promise<RaCruiseState> {
  return apiRequest<RaCruiseState>(`${RA_API_BASE}/cruise/toggle`, {
    method: "POST",
    body: JSON.stringify({ paused }),
  });
}
