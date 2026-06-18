"use client";

import { ApiError, apiRequest } from "@/lib/api";
import {
  normalizeExecutionProviderRegistryResponse,
  normalizeUserExecutionProvidersResponse,
  type ExecutionProviderRegistryResponse,
  type UserExecutionProvidersResponse,
} from "@/lib/execution-provider";

export type ExecutionProviderApiErrorSummary = {
  status: number | null;
  message: string;
  provider_access_unknown: boolean;
};

export type ExecutionProviderApiResult<T> = {
  ok: boolean;
  data: T;
  error: ExecutionProviderApiErrorSummary | null;
  provider_access_unknown: boolean;
};

export const EMPTY_EXECUTION_PROVIDER_REGISTRY_RESPONSE: ExecutionProviderRegistryResponse = {
  count: 0,
  items: [],
};

export const EMPTY_USER_EXECUTION_PROVIDERS_RESPONSE: UserExecutionProvidersResponse = {
  count: 0,
  is_owner_full_access: false,
  items: [],
  role: "",
  user_id: 0,
};

export function formatExecutionProviderApiError(
  error: unknown,
): ExecutionProviderApiErrorSummary {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return {
        message: "Please sign in again to read Execution Provider status.",
        provider_access_unknown: true,
        status: 401,
      };
    }
    if (error.status === 403) {
      return {
        message: "Current account cannot read Execution Provider status.",
        provider_access_unknown: true,
        status: 403,
      };
    }
    if (error.status === 404) {
      return {
        message: "Execution Provider API is unavailable.",
        provider_access_unknown: true,
        status: 404,
      };
    }
    if (error.status >= 500) {
      return {
        message: "Backend Execution Provider service is unavailable.",
        provider_access_unknown: true,
        status: error.status,
      };
    }
    return {
      message:
        "Execution Provider status request failed; frontend is using a safe unavailable state.",
      provider_access_unknown: true,
      status: error.status,
    };
  }

  return {
    message:
      "Execution Provider status request failed; frontend is using a safe unavailable state.",
    provider_access_unknown: true,
    status: null,
  };
}

export function executionProviderRegistryResultFromResponse(
  response: unknown,
): ExecutionProviderApiResult<ExecutionProviderRegistryResponse> {
  return {
    data: normalizeExecutionProviderRegistryResponse(response),
    error: null,
    ok: true,
    provider_access_unknown: false,
  };
}

export function executionProviderRegistryResultFromError(
  error: unknown,
): ExecutionProviderApiResult<ExecutionProviderRegistryResponse> {
  return {
    data: EMPTY_EXECUTION_PROVIDER_REGISTRY_RESPONSE,
    error: formatExecutionProviderApiError(error),
    ok: false,
    provider_access_unknown: true,
  };
}

export function userExecutionProvidersResultFromResponse(
  response: unknown,
): ExecutionProviderApiResult<UserExecutionProvidersResponse> {
  return {
    data: normalizeUserExecutionProvidersResponse(response),
    error: null,
    ok: true,
    provider_access_unknown: false,
  };
}

export function userExecutionProvidersResultFromError(
  error: unknown,
): ExecutionProviderApiResult<UserExecutionProvidersResponse> {
  return {
    data: EMPTY_USER_EXECUTION_PROVIDERS_RESPONSE,
    error: formatExecutionProviderApiError(error),
    ok: false,
    provider_access_unknown: true,
  };
}

export async function getExecutionProviderRegistry(): Promise<
  ExecutionProviderApiResult<ExecutionProviderRegistryResponse>
> {
  try {
    const response = await apiRequest<unknown>("/execution-providers/registry", {
      method: "GET",
    });
    return executionProviderRegistryResultFromResponse(response);
  } catch (error) {
    return executionProviderRegistryResultFromError(error);
  }
}

export async function getMyExecutionProviders(): Promise<
  ExecutionProviderApiResult<UserExecutionProvidersResponse>
> {
  try {
    const response = await apiRequest<unknown>("/execution-providers/me", {
      method: "GET",
    });
    return userExecutionProvidersResultFromResponse(response);
  } catch (error) {
    return userExecutionProvidersResultFromError(error);
  }
}
