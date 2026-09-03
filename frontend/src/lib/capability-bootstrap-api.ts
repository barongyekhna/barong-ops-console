"use client";

import { ApiError, apiRequest, isApiAbortError } from "@/lib/api";
import {
  executionProviderRegistryResultFromError,
  executionProviderRegistryResultFromResponse,
  getExecutionProviderRegistry,
  getMyExecutionProviders,
  userExecutionProvidersResultFromError,
  userExecutionProvidersResultFromResponse,
  type ExecutionProviderApiResult,
} from "@/lib/execution-provider-api";
import type {
  ExecutionProviderRegistryResponse,
  UserExecutionProvidersResponse,
} from "@/lib/execution-provider";
import {
  getPreLiveReadiness,
  getProductionReadiness,
  listLiveGatePolicies,
  liveGatePoliciesResultFromError,
  liveGatePoliciesResultFromResponse,
  preLiveReadinessResultFromError,
  preLiveReadinessResultFromResponse,
  productionReadinessResultFromError,
  productionReadinessResultFromResponse,
  type LiveGateApiResult,
} from "@/lib/live-gate-api";
import type {
  LiveGatePolicyRead,
  PreLiveValidationReport,
  ProductionReadinessReport,
} from "@/lib/live-gate";
import {
  listModuleAdapterRegistry,
  listMyModuleAdapters,
  moduleAdapterRegistryResultFromError,
  moduleAdapterRegistryResultFromResponse,
  userModuleAdaptersResultFromError,
  userModuleAdaptersResultFromResponse,
  type ModuleAdapterApiResult,
} from "@/lib/module-adapter-api";
import type {
  ModuleAdapterRegistryResponse,
  UserModuleAdaptersResponse,
} from "@/lib/module-adapter";
import {
  formatModuleApiError,
  listModuleRegistry,
  listMyModules,
  moduleRegistryResultFromError,
  moduleRegistryResultFromResponse,
  type ModuleApiErrorSummary,
  userModulesResultFromError,
  userModulesResultFromResponse,
  type ModuleApiResult,
} from "@/lib/module-registry-api";
import type {
  ModuleRegistryResponse,
  UserModulesResponse,
} from "@/lib/module-registry";
import type { ModuleControlCenterResponse } from "@/lib/module-control-api";

type CapabilityBootstrapEntry = {
  ok?: boolean;
  status?: number | null;
  data?: unknown;
  detail?: unknown;
  // 后端标记「这一项是有意不在批量里查的」（status 204）。
  // 不是故障，不能算进降级判定。
  deferred?: boolean;
};

type CapabilityBootstrapPayload = {
  execution_providers_me?: CapabilityBootstrapEntry;
  execution_providers_registry?: CapabilityBootstrapEntry;
  live_gate_policies?: CapabilityBootstrapEntry;
  live_gate_production_readiness?: CapabilityBootstrapEntry;
  live_gate_readiness?: CapabilityBootstrapEntry;
  module_adapters_me?: CapabilityBootstrapEntry;
  module_adapters_registry?: CapabilityBootstrapEntry;
  module_control_center?: CapabilityBootstrapEntry;
  modules_me?: CapabilityBootstrapEntry;
  modules_registry?: CapabilityBootstrapEntry;
};

type CapabilityBootstrapOptions = {
  forceRefresh?: boolean;
  signal?: AbortSignal;
  timeoutMs?: number;
};

const CAPABILITY_BOOTSTRAP_TIMEOUT_MS = 30_000;

export type CapabilityBootstrapResult = {
  adapterAccessResult: ModuleAdapterApiResult<UserModuleAdaptersResponse>;
  adapterRegistryResult: ModuleAdapterApiResult<ModuleAdapterRegistryResponse>;
  executionAccessResult: ExecutionProviderApiResult<UserExecutionProvidersResponse>;
  executionRegistryResult: ExecutionProviderApiResult<ExecutionProviderRegistryResponse>;
  moduleAccessResult: ModuleApiResult<UserModulesResponse>;
  moduleControlResult: ModuleApiResult<ModuleControlCenterResponse>;
  policiesResult: LiveGateApiResult<LiveGatePolicyRead[]>;
  productionResult: LiveGateApiResult<ProductionReadinessReport>;
  readinessResult: LiveGateApiResult<PreLiveValidationReport>;
  registryResult: ModuleApiResult<ModuleRegistryResponse>;
};

const EMPTY_MODULE_CONTROL_CENTER: ModuleControlCenterResponse = {
  auto_registered_count: 0,
  module_count: 0,
  organization_count: 0,
  organizations: [],
};

function moduleControlResultFromResponse(
  response: unknown,
): ModuleApiResult<ModuleControlCenterResponse> {
  const record =
    response && typeof response === "object"
      ? (response as Partial<ModuleControlCenterResponse>)
      : {};
  const organizations = Array.isArray(record.organizations)
    ? record.organizations
    : [];

  return {
    data: {
      auto_registered_count:
        typeof record.auto_registered_count === "number"
          ? record.auto_registered_count
          : 0,
      module_count:
        typeof record.module_count === "number"
          ? record.module_count
          : organizations.reduce(
              (count, organization) =>
                count +
                (Array.isArray(organization.modules)
                  ? organization.modules.length
                  : 0),
              0,
            ),
      organization_count:
        typeof record.organization_count === "number"
          ? record.organization_count
          : organizations.length,
      organizations,
    },
    error: null,
    module_access_unknown: false,
    ok: true,
  };
}

function moduleControlResultFromError(
  error: unknown,
): ModuleApiResult<ModuleControlCenterResponse> {
  return {
    data: EMPTY_MODULE_CONTROL_CENTER,
    error: formatModuleApiError(error) as ModuleApiErrorSummary,
    module_access_unknown: true,
    ok: false,
  };
}

function detailMessage(detail: unknown, fallback: string) {
  if (typeof detail === "string" && detail.trim().length > 0) {
    return detail;
  }

  if (
    detail &&
    typeof detail === "object" &&
    "detail" in detail &&
    typeof detail.detail === "string"
  ) {
    return detail.detail;
  }

  return fallback;
}

function entryError(entry: CapabilityBootstrapEntry | undefined) {
  return new ApiError(
    detailMessage(entry?.detail, "Capability bootstrap subrequest failed."),
    typeof entry?.status === "number" ? entry.status : 503,
  );
}

function dataOrError<T>(
  entry: CapabilityBootstrapEntry | undefined,
  fromResponse: (response: unknown) => T,
  fromError: (error: unknown) => T,
) {
  if (entry?.ok === true) {
    return fromResponse(entry.data);
  }

  // 把 deferred / status 一并带到结果上。
  // 2026-08-31：这里原本只把 entry 压成「成功值」或「失败值」两种形状，
  // status 和 deferred 在这一步就丢了 —— 于是上层无从区分
  // 「有意不查」「没权限」「真出故障」，只能把它们一律当成降级，
  // 侧边栏那句提示也就永远亮着。
  const result = fromError(entryError(entry));
  if (result != null && typeof result === "object") {
    return {
      ...(result as Record<string, unknown>),
      deferred: entry?.deferred === true,
      status: entry?.status ?? null,
    } as T;
  }
  return result;
}

async function fallbackCapabilityBootstrap(
  options: CapabilityBootstrapOptions = {},
): Promise<CapabilityBootstrapResult> {
  const [
    registryResult,
    moduleAccessResult,
    adapterRegistryResult,
    adapterAccessResult,
    executionRegistryResult,
    executionAccessResult,
    readinessResult,
    productionResult,
    policiesResult,
    moduleControlResult,
  ] = await Promise.all([
    listModuleRegistry(options),
    listMyModules(options),
    listModuleAdapterRegistry(options),
    listMyModuleAdapters(options),
    getExecutionProviderRegistry(options),
    getMyExecutionProviders(options),
    getPreLiveReadiness(options),
    getProductionReadiness(options),
    listLiveGatePolicies(options),
    Promise.resolve(
      moduleControlResultFromError(
        new ApiError(
          "Module control center is unavailable in fallback bootstrap.",
          503,
        ),
      ),
    ),
  ]);

  return {
    adapterAccessResult,
    adapterRegistryResult,
    executionAccessResult,
    executionRegistryResult,
    moduleAccessResult,
    moduleControlResult,
    policiesResult,
    productionResult,
    readinessResult,
    registryResult,
  };
}

export async function getCapabilityBootstrap(
  options: CapabilityBootstrapOptions = {},
): Promise<CapabilityBootstrapResult> {
  try {
    const payload = await apiRequest<CapabilityBootstrapPayload>(
      "/capability/bootstrap",
      {
        bypassCache: options.forceRefresh,
        method: "GET",
        signal: options.signal,
        timeoutMs: options.timeoutMs ?? CAPABILITY_BOOTSTRAP_TIMEOUT_MS,
      },
    );

    return {
      adapterAccessResult: dataOrError(
        payload.module_adapters_me,
        userModuleAdaptersResultFromResponse,
        userModuleAdaptersResultFromError,
      ),
      adapterRegistryResult: dataOrError(
        payload.module_adapters_registry,
        moduleAdapterRegistryResultFromResponse,
        moduleAdapterRegistryResultFromError,
      ),
      executionAccessResult: dataOrError(
        payload.execution_providers_me,
        userExecutionProvidersResultFromResponse,
        userExecutionProvidersResultFromError,
      ),
      executionRegistryResult: dataOrError(
        payload.execution_providers_registry,
        executionProviderRegistryResultFromResponse,
        executionProviderRegistryResultFromError,
      ),
      moduleAccessResult: dataOrError(
        payload.modules_me,
        userModulesResultFromResponse,
        userModulesResultFromError,
      ),
      moduleControlResult: dataOrError(
        payload.module_control_center,
        moduleControlResultFromResponse,
        moduleControlResultFromError,
      ),
      policiesResult: dataOrError(
        payload.live_gate_policies,
        liveGatePoliciesResultFromResponse,
        liveGatePoliciesResultFromError,
      ),
      productionResult: dataOrError(
        payload.live_gate_production_readiness,
        productionReadinessResultFromResponse,
        productionReadinessResultFromError,
      ),
      readinessResult: dataOrError(
        payload.live_gate_readiness,
        preLiveReadinessResultFromResponse,
        preLiveReadinessResultFromError,
      ),
      registryResult: dataOrError(
        payload.modules_registry,
        moduleRegistryResultFromResponse,
        moduleRegistryResultFromError,
      ),
    };
  } catch (error) {
    if (isApiAbortError(error)) {
      throw error;
    }

    return fallbackCapabilityBootstrap(options);
  }
}
