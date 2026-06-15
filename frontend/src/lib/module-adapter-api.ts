"use client";

import { ApiError, apiRequest } from "@/lib/api";
import {
  normalizeModuleAdapterRegistryResponse,
  normalizeUserModuleAdaptersResponse,
  type ModuleAdapterRegistryResponse,
  type UserModuleAdaptersResponse,
} from "@/lib/module-adapter";

export type ModuleAdapterApiErrorSummary = {
  status: number | null;
  message: string;
  adapter_access_unknown: boolean;
};

export type ModuleAdapterApiResult<T> = {
  ok: boolean;
  data: T;
  error: ModuleAdapterApiErrorSummary | null;
  adapter_access_unknown: boolean;
};

const EMPTY_REGISTRY_RESPONSE: ModuleAdapterRegistryResponse = {
  count: 0,
  items: [],
};

const EMPTY_USER_ADAPTERS_RESPONSE: UserModuleAdaptersResponse = {
  count: 0,
  is_owner_full_access: false,
  items: [],
  role: "",
  user_id: 0,
};

function formatModuleAdapterApiError(
  error: unknown,
): ModuleAdapterApiErrorSummary {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return {
        adapter_access_unknown: true,
        message: "请重新登录后再读取 adapter 状态。",
        status: 401,
      };
    }
    if (error.status === 403) {
      return {
        adapter_access_unknown: true,
        message: "当前账号无权读取 adapter 状态。",
        status: 403,
      };
    }
    if (error.status === 404) {
      return {
        adapter_access_unknown: true,
        message: "Adapter registry API 暂不可用。",
        status: 404,
      };
    }
    if (error.status >= 500) {
      return {
        adapter_access_unknown: true,
        message: "后端 adapter registry 服务暂不可用。",
        status: error.status,
      };
    }
    return {
      adapter_access_unknown: true,
      message: "Adapter 状态请求失败，前端已切换为安全降级。",
      status: error.status,
    };
  }

  return {
    adapter_access_unknown: true,
    message: "Adapter 状态请求失败，前端已切换为安全降级。",
    status: null,
  };
}

export async function listModuleAdapterRegistry(): Promise<
  ModuleAdapterApiResult<ModuleAdapterRegistryResponse>
> {
  try {
    const response = await apiRequest<unknown>("/module-adapters/registry", {
      method: "GET",
    });
    return {
      adapter_access_unknown: false,
      data: normalizeModuleAdapterRegistryResponse(response),
      error: null,
      ok: true,
    };
  } catch (error) {
    return {
      adapter_access_unknown: true,
      data: EMPTY_REGISTRY_RESPONSE,
      error: formatModuleAdapterApiError(error),
      ok: false,
    };
  }
}

export async function listMyModuleAdapters(): Promise<
  ModuleAdapterApiResult<UserModuleAdaptersResponse>
> {
  try {
    const response = await apiRequest<unknown>("/module-adapters/me", {
      method: "GET",
    });
    return {
      adapter_access_unknown: false,
      data: normalizeUserModuleAdaptersResponse(response),
      error: null,
      ok: true,
    };
  } catch (error) {
    return {
      adapter_access_unknown: true,
      data: EMPTY_USER_ADAPTERS_RESPONSE,
      error: formatModuleAdapterApiError(error),
      ok: false,
    };
  }
}
