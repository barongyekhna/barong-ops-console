"use client";

import { ApiError, apiRequest } from "@/lib/api";
import { readAccessToken } from "@/lib/auth";
import {
  normalizeModuleRegistryResponse,
  normalizeUserModulesResponse,
  type ModuleRegistryResponse,
  type UserModulesResponse,
} from "@/lib/module-registry";

export type ModuleApiErrorSummary = {
  status: number | null;
  message: string;
  module_access_unknown: boolean;
};

export type ModuleApiResult<T> = {
  ok: boolean;
  data: T;
  error: ModuleApiErrorSummary | null;
  module_access_unknown: boolean;
};

const EMPTY_REGISTRY_RESPONSE: ModuleRegistryResponse = {
  count: 0,
  items: [],
};
const EMPTY_USER_MODULES_RESPONSE: UserModulesResponse = {
  count: 0,
  is_owner_full_access: false,
  items: [],
  role: "",
  user_id: 0,
};

function formatModuleApiError(error: unknown): ModuleApiErrorSummary {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return {
        message: "请重新登录后再读取模块状态。",
        module_access_unknown: true,
        status: 401,
      };
    }
    if (error.status === 403) {
      return {
        message: "当前账号无权读取模块状态。",
        module_access_unknown: true,
        status: 403,
      };
    }
    if (error.status === 404) {
      return {
        message: "模块状态 API 暂不可用。",
        module_access_unknown: true,
        status: 404,
      };
    }
    if (error.status >= 500) {
      return {
        message: "后端模块状态服务暂不可用。",
        module_access_unknown: true,
        status: error.status,
      };
    }
    return {
      message: "模块状态请求失败，前端已切换为安全降级。",
      module_access_unknown: true,
      status: error.status,
    };
  }

  return {
    message: "模块状态请求失败，前端已切换为安全降级。",
    module_access_unknown: true,
    status: null,
  };
}

export async function listModuleRegistry(): Promise<
  ModuleApiResult<ModuleRegistryResponse>
> {
  try {
    const response = await apiRequest<unknown>("/modules/registry", {
      accessToken: readAccessToken(),
      method: "GET",
    });
    return {
      data: normalizeModuleRegistryResponse(response),
      error: null,
      module_access_unknown: false,
      ok: true,
    };
  } catch (error) {
    return {
      data: EMPTY_REGISTRY_RESPONSE,
      error: formatModuleApiError(error),
      module_access_unknown: true,
      ok: false,
    };
  }
}

export async function listMyModules(): Promise<
  ModuleApiResult<UserModulesResponse>
> {
  try {
    const response = await apiRequest<unknown>("/modules/me", {
      accessToken: readAccessToken(),
      method: "GET",
    });
    return {
      data: normalizeUserModulesResponse(response),
      error: null,
      module_access_unknown: false,
      ok: true,
    };
  } catch (error) {
    return {
      data: EMPTY_USER_MODULES_RESPONSE,
      error: formatModuleApiError(error),
      module_access_unknown: true,
      ok: false,
    };
  }
}
