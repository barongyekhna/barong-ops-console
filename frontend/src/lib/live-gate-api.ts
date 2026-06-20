"use client";

import { ApiError, apiRequest } from "@/lib/api";
import {
  normalizeLiveGatePolicies,
  normalizePreLiveValidationReport,
  normalizeProductionReadinessReport,
  type LiveGatePolicyRead,
  type PreLiveValidationReport,
  type ProductionReadinessReport,
} from "@/lib/live-gate";

type LiveGateRequestOptions = {
  signal?: AbortSignal;
  timeoutMs?: number;
};

export type LiveGateApiErrorSummary = {
  status: number | null;
  message: string;
  live_gate_unknown: boolean;
};

export type LiveGateApiResult<T> = {
  ok: boolean;
  data: T;
  error: LiveGateApiErrorSummary | null;
  live_gate_unknown: boolean;
};

export const EMPTY_PRE_LIVE_REPORT: PreLiveValidationReport = {
  checks: [],
  engine: "PreLiveValidationEngine",
  generated_at: null,
  passed: false,
};

export const EMPTY_PRODUCTION_REPORT: ProductionReadinessReport = {
  checks: [],
  engine: "ProductionReadinessEngine",
  generated_at: null,
  ready: false,
};

export function formatLiveGateApiError(error: unknown): LiveGateApiErrorSummary {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return {
        live_gate_unknown: true,
        message: "Please sign in again to read PRE20-Q live gate status.",
        status: 401,
      };
    }
    if (error.status === 403) {
      return {
        live_gate_unknown: true,
        message: "Current account cannot read PRE20-Q live gate status.",
        status: 403,
      };
    }
    if (error.status === 404) {
      return {
        live_gate_unknown: true,
        message: "PRE20-Q live gate API is unavailable.",
        status: 404,
      };
    }
    if (error.status >= 500) {
      return {
        live_gate_unknown: true,
        message: "Backend PRE20-Q live gate service is unavailable.",
        status: error.status,
      };
    }
    return {
      live_gate_unknown: true,
      message:
        "PRE20-Q live gate request failed; frontend is using a blocked state.",
      status: error.status,
    };
  }

  return {
    live_gate_unknown: true,
    message:
      "PRE20-Q live gate request failed; frontend is using a blocked state.",
    status: null,
  };
}

export function preLiveReadinessResultFromResponse(
  response: unknown,
): LiveGateApiResult<PreLiveValidationReport> {
  return {
    data: normalizePreLiveValidationReport(response),
    error: null,
    live_gate_unknown: false,
    ok: true,
  };
}

export function preLiveReadinessResultFromError(
  error: unknown,
): LiveGateApiResult<PreLiveValidationReport> {
  return {
    data: EMPTY_PRE_LIVE_REPORT,
    error: formatLiveGateApiError(error),
    live_gate_unknown: true,
    ok: false,
  };
}

export function productionReadinessResultFromResponse(
  response: unknown,
): LiveGateApiResult<ProductionReadinessReport> {
  return {
    data: normalizeProductionReadinessReport(response),
    error: null,
    live_gate_unknown: false,
    ok: true,
  };
}

export function productionReadinessResultFromError(
  error: unknown,
): LiveGateApiResult<ProductionReadinessReport> {
  return {
    data: EMPTY_PRODUCTION_REPORT,
    error: formatLiveGateApiError(error),
    live_gate_unknown: true,
    ok: false,
  };
}

export function liveGatePoliciesResultFromResponse(
  response: unknown,
): LiveGateApiResult<LiveGatePolicyRead[]> {
  return {
    data: normalizeLiveGatePolicies(response),
    error: null,
    live_gate_unknown: false,
    ok: true,
  };
}

export function liveGatePoliciesResultFromError(
  error: unknown,
): LiveGateApiResult<LiveGatePolicyRead[]> {
  return {
    data: [],
    error: formatLiveGateApiError(error),
    live_gate_unknown: true,
    ok: false,
  };
}

export async function getPreLiveReadiness(
  options: LiveGateRequestOptions = {},
): Promise<LiveGateApiResult<PreLiveValidationReport>> {
  try {
    const response = await apiRequest<unknown>("/live-gate/readiness", {
      method: "GET",
      signal: options.signal,
      timeoutMs: options.timeoutMs,
    });
    return preLiveReadinessResultFromResponse(response);
  } catch (error) {
    return preLiveReadinessResultFromError(error);
  }
}

export async function getProductionReadiness(
  options: LiveGateRequestOptions = {},
): Promise<LiveGateApiResult<ProductionReadinessReport>> {
  try {
    const response = await apiRequest<unknown>(
      "/live-gate/production-readiness",
      {
        method: "GET",
        signal: options.signal,
        timeoutMs: options.timeoutMs,
      },
    );
    return productionReadinessResultFromResponse(response);
  } catch (error) {
    return productionReadinessResultFromError(error);
  }
}

export async function listLiveGatePolicies(
  options: LiveGateRequestOptions = {},
): Promise<LiveGateApiResult<LiveGatePolicyRead[]>> {
  try {
    const response = await apiRequest<unknown>("/live-gate/policies", {
      method: "GET",
      signal: options.signal,
      timeoutMs: options.timeoutMs,
    });
    return liveGatePoliciesResultFromResponse(response);
  } catch (error) {
    return liveGatePoliciesResultFromError(error);
  }
}
