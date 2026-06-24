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
  listModuleRegistry,
  listMyModules,
  moduleRegistryResultFromError,
  moduleRegistryResultFromResponse,
  userModulesResultFromError,
  userModulesResultFromResponse,
  type ModuleApiResult,
} from "@/lib/module-registry-api";
import type {
  ModuleRegistryResponse,
  UserModulesResponse,
} from "@/lib/module-registry";

type CapabilityBootstrapEntry = {
  ok?: boolean;
  status?: number | null;
  data?: unknown;
  detail?: unknown;
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
  policiesResult: LiveGateApiResult<LiveGatePolicyRead[]>;
  productionResult: LiveGateApiResult<ProductionReadinessReport>;
  readinessResult: LiveGateApiResult<PreLiveValidationReport>;
  registryResult: ModuleApiResult<ModuleRegistryResponse>;
};

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

  return fromError(entryError(entry));
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
  ]);

  return {
    adapterAccessResult,
    adapterRegistryResult,
    executionAccessResult,
    executionRegistryResult,
    moduleAccessResult,
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
