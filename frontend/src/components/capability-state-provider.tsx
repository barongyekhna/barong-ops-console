"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { useAdapterAccess } from "@/components/adapter-access-provider";
import { useAuth } from "@/components/auth-provider";
import { useModuleAccess } from "@/components/module-access-provider";
import {
  buildFrontendCapabilityGraph,
  findCapabilityForPath,
  type FrontendCapabilityGraph,
  type ProductCapabilityItem,
} from "@/lib/frontend-capability-state";
import {
  getPreLiveReadiness,
  getProductionReadiness,
  listLiveGatePolicies,
  type LiveGateApiErrorSummary,
} from "@/lib/live-gate-api";
import {
  deriveLiveGateRuntimeState,
  type LiveGatePolicyRead,
  type LiveGateRuntimeState,
  type PreLiveValidationReport,
  type ProductionReadinessReport,
} from "@/lib/live-gate";
import {
  listModuleRegistry,
  type ModuleApiErrorSummary,
} from "@/lib/module-registry-api";
import type { ModuleManifest } from "@/lib/module-registry";

type CapabilityStateContextValue = FrontendCapabilityGraph & {
  isLoading: boolean;
  uiState: "loading" | "ready" | "degraded" | "fallback";
  isDegraded: boolean;
  isFallbackMode: boolean;
  registryItems: ModuleManifest[];
  registryUnavailable: boolean;
  registryError: ModuleApiErrorSummary | null;
  liveGate: LiveGateRuntimeState;
  liveGateErrors: {
    readiness: LiveGateApiErrorSummary | null;
    productionReadiness: LiveGateApiErrorSummary | null;
    policies: LiveGateApiErrorSummary | null;
  };
  liveGateReports: {
    readiness: PreLiveValidationReport | null;
    productionReadiness: ProductionReadinessReport | null;
    policies: LiveGatePolicyRead[];
  };
  getCapabilityForPath: (pathname: string) => ProductCapabilityItem | null;
  refresh: () => Promise<void>;
};

const CapabilityStateContext =
  createContext<CapabilityStateContextValue | null>(null);

const EMPTY_LIVE_GATE = deriveLiveGateRuntimeState({
  policies: [],
  policyError: "Action readiness has not loaded.",
  productionReadiness: null,
  productionReadinessError: "Production readiness has not loaded.",
  readiness: null,
  readinessError: "Readiness has not loaded.",
});

const SAFE_MODULE_ACCESS: ReturnType<typeof useModuleAccess> = {
  error: null,
  isLoading: false,
  items: [],
  moduleAccessUnknown: true,
  refresh: async () => {},
};

const SAFE_ADAPTER_ACCESS: ReturnType<typeof useAdapterAccess> = {
  accessItems: [],
  adapterAccessUnknown: true,
  adapterMetadataUnavailable: true,
  adapters: [],
  error: null,
  executionProviderAccessItems: [],
  executionProviderAccessUnknown: true,
  executionProviderError: null,
  executionProviderMetadataUnavailable: true,
  executionProviderRegistryError: null,
  executionProviders: [],
  isLoading: false,
  refresh: async () => {},
  registryError: null,
};

const SAFE_REGISTRY_ERROR: ModuleApiErrorSummary = {
  message: "Capability state is running in fallback mode.",
  module_access_unknown: true,
  status: null,
};

const SAFE_LIVE_GATE_ERROR: LiveGateApiErrorSummary = {
  live_gate_unknown: true,
  message: "Action readiness is running in fallback mode.",
  status: null,
};

const SAFE_READINESS_REPORT: PreLiveValidationReport = {
  checks: [],
  engine: "PreLiveValidationEngine",
  generated_at: null,
  passed: false,
};

const SAFE_PRODUCTION_READINESS_REPORT: ProductionReadinessReport = {
  checks: [],
  engine: "ProductionReadinessEngine",
  generated_at: null,
  ready: false,
};

function safeArray<T>(value: readonly T[] | null | undefined): T[] {
  return Array.isArray(value) ? [...value] : [];
}

function safeModuleAccess(
  value: ReturnType<typeof useModuleAccess> | null | undefined,
) {
  return {
    ...SAFE_MODULE_ACCESS,
    ...(value ?? {}),
    error: value?.error ?? null,
    isLoading: value?.isLoading === true,
    items: safeArray(value?.items),
    moduleAccessUnknown: value?.moduleAccessUnknown !== false,
    refresh: value?.refresh ?? SAFE_MODULE_ACCESS.refresh,
  };
}

function safeAdapterAccess(
  value: ReturnType<typeof useAdapterAccess> | null | undefined,
) {
  return {
    ...SAFE_ADAPTER_ACCESS,
    ...(value ?? {}),
    accessItems: safeArray(value?.accessItems),
    adapterAccessUnknown: value?.adapterAccessUnknown !== false,
    adapterMetadataUnavailable: value?.adapterMetadataUnavailable !== false,
    adapters: safeArray(value?.adapters),
    error: value?.error ?? null,
    executionProviderAccessItems: safeArray(value?.executionProviderAccessItems),
    executionProviderAccessUnknown:
      value?.executionProviderAccessUnknown !== false,
    executionProviderError: value?.executionProviderError ?? null,
    executionProviderMetadataUnavailable:
      value?.executionProviderMetadataUnavailable !== false,
    executionProviderRegistryError:
      value?.executionProviderRegistryError ?? null,
    executionProviders: safeArray(value?.executionProviders),
    isLoading: value?.isLoading === true,
    refresh: value?.refresh ?? SAFE_ADAPTER_ACCESS.refresh,
    registryError: value?.registryError ?? null,
  };
}

function createSafeGraph(liveGate: LiveGateRuntimeState = EMPTY_LIVE_GATE) {
  try {
    return buildFrontendCapabilityGraph({
      adapterAccessItems: [],
      adapterAccessUnknown: true,
      adapterContracts: [],
      executionProviderAccessItems: [],
      executionProviderAccessUnknown: true,
      executionProviderContracts: [],
      liveGate,
      moduleAccessItems: [],
      moduleAccessUnknown: true,
      permissions: null,
      registryItems: [],
      registryUnavailable: true,
      role: "",
    });
  } catch {
    return {
      byModuleKey: new Map(),
      executionState: {
        adapter_count: 0,
        adapter_pending_count: 0,
        approval_state: "unknown" as const,
        blocked_reason: liveGate.blocked_reason,
        canary_state: liveGate.canary_state,
        execution_mode: liveGate.execution_mode,
        live_gate_status: liveGate.live_gate_status,
        no_execution_count: 0,
        production_ready: false,
        provider_count: 0,
        readiness_passed: false,
        rollout_percentage: 0,
        source: "safe-default",
      },
      groups: [],
      items: [],
      orgContext: {
        hidden_modules: 0,
        reason: "Workspace organization access is in fallback mode.",
        role: "",
        source: "/modules/me" as const,
        state: "unknown" as const,
        visible_modules: 0,
      },
      permissionSnapshot: {
        is_owner_full_access: false,
        permission_count: 0,
        permissions: [],
        source: "/auth/me" as const,
      },
      sidebarItems: [],
    };
  }
}

const SAFE_GRAPH = createSafeGraph();

const SAFE_CONTEXT_VALUE: CapabilityStateContextValue = {
  ...SAFE_GRAPH,
  getCapabilityForPath: (pathname: string) =>
    findCapabilityForPath(pathname, SAFE_GRAPH.items),
  isDegraded: true,
  isFallbackMode: true,
  isLoading: false,
  liveGate: EMPTY_LIVE_GATE,
  liveGateErrors: {
    policies: SAFE_LIVE_GATE_ERROR,
    productionReadiness: SAFE_LIVE_GATE_ERROR,
    readiness: SAFE_LIVE_GATE_ERROR,
  },
  liveGateReports: {
    policies: [],
    productionReadiness: SAFE_PRODUCTION_READINESS_REPORT,
    readiness: SAFE_READINESS_REPORT,
  },
  refresh: async () => {},
  registryError: SAFE_REGISTRY_ERROR,
  registryItems: [],
  registryUnavailable: true,
  uiState: "fallback",
};

function safeContext(
  state: CapabilityStateContextValue | null | undefined,
): CapabilityStateContextValue {
  return state ?? SAFE_CONTEXT_VALUE;
}

export function CapabilityStateProvider({
  children,
}: {
  children: ReactNode;
}) {
  const auth = useAuth();
  const status = auth?.status ?? "unauthenticated";
  const user = auth?.user ?? null;
  const moduleAccess = safeModuleAccess(useModuleAccess());
  const adapterAccess = safeAdapterAccess(useAdapterAccess());
  const [registryItems, setRegistryItems] = useState<ModuleManifest[]>([]);
  const [registryUnavailable, setRegistryUnavailable] = useState(true);
  const [registryError, setRegistryError] =
    useState<ModuleApiErrorSummary | null>(SAFE_REGISTRY_ERROR);
  const [readiness, setReadiness] =
    useState<PreLiveValidationReport | null>(SAFE_READINESS_REPORT);
  const [productionReadiness, setProductionReadiness] =
    useState<ProductionReadinessReport | null>(
      SAFE_PRODUCTION_READINESS_REPORT,
    );
  const [policies, setPolicies] = useState<LiveGatePolicyRead[]>([]);
  const [readinessError, setReadinessError] =
    useState<LiveGateApiErrorSummary | null>(SAFE_LIVE_GATE_ERROR);
  const [productionReadinessError, setProductionReadinessError] =
    useState<LiveGateApiErrorSummary | null>(SAFE_LIVE_GATE_ERROR);
  const [policiesError, setPoliciesError] =
    useState<LiveGateApiErrorSummary | null>(SAFE_LIVE_GATE_ERROR);
  const [isLocalLoading, setIsLocalLoading] = useState(false);
  const [isFallbackMode, setIsFallbackMode] = useState(true);

  const loadCapabilityState = useCallback(async () => {
    if (status !== "authenticated" || !user) {
      setRegistryItems([]);
      setRegistryUnavailable(true);
      setRegistryError(SAFE_REGISTRY_ERROR);
      setReadiness(SAFE_READINESS_REPORT);
      setProductionReadiness(SAFE_PRODUCTION_READINESS_REPORT);
      setPolicies([]);
      setReadinessError(SAFE_LIVE_GATE_ERROR);
      setProductionReadinessError(SAFE_LIVE_GATE_ERROR);
      setPoliciesError(SAFE_LIVE_GATE_ERROR);
      setIsLocalLoading(false);
      setIsFallbackMode(true);
      return;
    }

    setIsLocalLoading(true);
    try {
      const [
        registryResult,
        readinessResult,
        productionResult,
        policiesResult,
      ] = await Promise.all([
        listModuleRegistry(),
        getPreLiveReadiness(),
        getProductionReadiness(),
        listLiveGatePolicies(),
      ]);

      setRegistryItems(safeArray(registryResult?.data?.items));
      setRegistryUnavailable(registryResult?.ok !== true);
      setRegistryError(registryResult?.error ?? null);
      setReadiness(
        readinessResult?.ok ? readinessResult.data : SAFE_READINESS_REPORT,
      );
      setProductionReadiness(
        productionResult?.ok
          ? productionResult.data
          : SAFE_PRODUCTION_READINESS_REPORT,
      );
      setPolicies(policiesResult?.ok ? safeArray(policiesResult.data) : []);
      setReadinessError(readinessResult?.error ?? null);
      setProductionReadinessError(productionResult?.error ?? null);
      setPoliciesError(policiesResult?.error ?? null);
      setIsFallbackMode(false);
    } catch {
      setRegistryItems([]);
      setRegistryUnavailable(true);
      setRegistryError(SAFE_REGISTRY_ERROR);
      setReadiness(SAFE_READINESS_REPORT);
      setProductionReadiness(SAFE_PRODUCTION_READINESS_REPORT);
      setPolicies([]);
      setReadinessError(SAFE_LIVE_GATE_ERROR);
      setProductionReadinessError(SAFE_LIVE_GATE_ERROR);
      setPoliciesError(SAFE_LIVE_GATE_ERROR);
      setIsFallbackMode(true);
    } finally {
      setIsLocalLoading(false);
    }
  }, [status, user]);

  useEffect(() => {
    let active = true;

    async function refreshWhenActive() {
      if (!active) {
        return;
      }
      await loadCapabilityState();
    }

    void refreshWhenActive();

    return () => {
      active = false;
    };
  }, [loadCapabilityState]);

  const refresh = useCallback(async () => {
    await Promise.allSettled([
      loadCapabilityState(),
      moduleAccess.refresh(),
      adapterAccess.refresh(),
    ]);
  }, [adapterAccess, loadCapabilityState, moduleAccess]);

  const liveGate = useMemo(
    () =>
      readiness || productionReadiness || policies.length > 0
        ? deriveLiveGateRuntimeState({
            policies,
            policyError: policiesError?.message,
            productionReadiness,
            productionReadinessError: productionReadinessError?.message,
            readiness,
            readinessError: readinessError?.message,
          })
        : EMPTY_LIVE_GATE,
    [
      policies,
      policiesError?.message,
      productionReadiness,
      productionReadinessError?.message,
      readiness,
      readinessError?.message,
    ],
  );

  const graph = useMemo(
    () => {
      try {
        return buildFrontendCapabilityGraph({
          adapterAccessItems: safeArray(adapterAccess.accessItems),
          adapterAccessUnknown: adapterAccess.adapterAccessUnknown,
          adapterContracts: safeArray(adapterAccess.adapters),
          executionProviderAccessItems: safeArray(
            adapterAccess.executionProviderAccessItems,
          ),
          executionProviderAccessUnknown:
            adapterAccess.executionProviderAccessUnknown,
          executionProviderContracts: safeArray(adapterAccess.executionProviders),
          liveGate,
          moduleAccessItems: safeArray(moduleAccess.items),
          moduleAccessUnknown: moduleAccess.moduleAccessUnknown,
          permissions: user?.permissions,
          registryItems: safeArray(registryItems),
          registryUnavailable,
          role: user?.role ?? "",
        });
      } catch {
        return createSafeGraph(liveGate);
      }
    },
    [
      adapterAccess.accessItems,
      adapterAccess.adapterAccessUnknown,
      adapterAccess.adapters,
      adapterAccess.executionProviderAccessItems,
      adapterAccess.executionProviderAccessUnknown,
      adapterAccess.executionProviders,
      liveGate,
      moduleAccess.items,
      moduleAccess.moduleAccessUnknown,
      registryItems,
      registryUnavailable,
      user?.permissions,
      user?.role,
    ],
  );

  const getCapabilityForPath = useCallback(
    (pathname: string) => findCapabilityForPath(pathname, graph.items),
    [graph.items],
  );

  const isLoading =
    status === "checking" ||
    isLocalLoading ||
    moduleAccess.isLoading ||
    adapterAccess.isLoading;
  const isDegraded =
    isFallbackMode ||
    registryUnavailable ||
    Boolean(registryError) ||
    Boolean(moduleAccess.error) ||
    Boolean(adapterAccess.error) ||
    Boolean(adapterAccess.registryError) ||
    Boolean(adapterAccess.executionProviderError) ||
    Boolean(adapterAccess.executionProviderRegistryError) ||
    Boolean(readinessError) ||
    Boolean(productionReadinessError) ||
    Boolean(policiesError) ||
    moduleAccess.moduleAccessUnknown ||
    adapterAccess.adapterAccessUnknown ||
    adapterAccess.executionProviderAccessUnknown;
  const uiState: CapabilityStateContextValue["uiState"] = isLoading
    ? "loading"
    : isFallbackMode
      ? "fallback"
      : isDegraded
        ? "degraded"
        : "ready";

  const value = useMemo(
    () => ({
      ...graph,
      getCapabilityForPath,
      isDegraded,
      isFallbackMode,
      isLoading,
      liveGate,
      liveGateErrors: {
        policies: policiesError,
        productionReadiness: productionReadinessError,
        readiness: readinessError,
      },
      liveGateReports: {
        policies,
        productionReadiness,
        readiness,
      },
      refresh,
      registryError,
      registryItems,
      registryUnavailable,
      uiState,
    }),
    [
      getCapabilityForPath,
      graph,
      isDegraded,
      isFallbackMode,
      isLoading,
      liveGate,
      policies,
      policiesError,
      productionReadiness,
      productionReadinessError,
      readiness,
      readinessError,
      refresh,
      registryError,
      registryItems,
      registryUnavailable,
      uiState,
    ],
  );

  return (
    <CapabilityStateContext.Provider value={value}>
      {children}
    </CapabilityStateContext.Provider>
  );
}

export function useFrontendCapabilityState() {
  const context = useContext(CapabilityStateContext);
  return safeContext(context);
}
