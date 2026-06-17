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

const EMPTY_PRE_LIVE_REPORT: PreLiveValidationReport = {
  checks: [],
  engine: "PreLiveValidationEngine",
  generated_at: null,
  passed: false,
};

const EMPTY_PRODUCTION_REPORT: ProductionReadinessReport = {
  checks: [],
  engine: "ProductionReadinessEngine",
  generated_at: null,
  ready: false,
};

function formatLiveGateApiError(error: unknown): LiveGateApiErrorSummary {
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

export async function getPreLiveReadiness(): Promise<
  LiveGateApiResult<PreLiveValidationReport>
> {
  try {
    const response = await apiRequest<unknown>("/live-gate/readiness", {
      method: "GET",
    });
    return {
      data: normalizePreLiveValidationReport(response),
      error: null,
      live_gate_unknown: false,
      ok: true,
    };
  } catch (error) {
    return {
      data: EMPTY_PRE_LIVE_REPORT,
      error: formatLiveGateApiError(error),
      live_gate_unknown: true,
      ok: false,
    };
  }
}

export async function getProductionReadiness(): Promise<
  LiveGateApiResult<ProductionReadinessReport>
> {
  try {
    const response = await apiRequest<unknown>(
      "/live-gate/production-readiness",
      { method: "GET" },
    );
    return {
      data: normalizeProductionReadinessReport(response),
      error: null,
      live_gate_unknown: false,
      ok: true,
    };
  } catch (error) {
    return {
      data: EMPTY_PRODUCTION_REPORT,
      error: formatLiveGateApiError(error),
      live_gate_unknown: true,
      ok: false,
    };
  }
}

export async function listLiveGatePolicies(): Promise<
  LiveGateApiResult<LiveGatePolicyRead[]>
> {
  try {
    const response = await apiRequest<unknown>("/live-gate/policies", {
      method: "GET",
    });
    return {
      data: normalizeLiveGatePolicies(response),
      error: null,
      live_gate_unknown: false,
      ok: true,
    };
  } catch (error) {
    return {
      data: [],
      error: formatLiveGateApiError(error),
      live_gate_unknown: true,
      ok: false,
    };
  }
}
