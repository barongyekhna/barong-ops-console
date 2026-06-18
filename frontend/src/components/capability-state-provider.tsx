"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useAuth } from "@/components/auth-provider";
import { getCapabilityBootstrap } from "@/lib/capability-bootstrap-api";
import type { ExecutionProviderApiErrorSummary } from "@/lib/execution-provider-api";
import type {
  ExecutionProviderAccessState,
  ExecutionProviderContract,
} from "@/lib/execution-provider";
import {
  buildFrontendCapabilityGraph,
  findCapabilityForPath,
  type FrontendCapabilityGraph,
  type ProductCapabilityItem,
} from "@/lib/frontend-capability-state";
import type { LiveGateApiErrorSummary } from "@/lib/live-gate-api";
import {
  deriveLiveGateRuntimeState,
  type LiveGatePolicyRead,
  type LiveGateRuntimeState,
  type PreLiveValidationReport,
  type ProductionReadinessReport,
} from "@/lib/live-gate";
import type { ModuleAdapterApiErrorSummary } from "@/lib/module-adapter-api";
import type {
  ModuleAdapterAccessState,
  ModuleAdapterContract,
} from "@/lib/module-adapter";
import type { ModuleApiErrorSummary } from "@/lib/module-registry-api";
import type { ModuleAccessState, ModuleManifest } from "@/lib/module-registry";

type CapabilityStateContextValue = FrontendCapabilityGraph & {
  adapterAccessItems: ModuleAdapterAccessState[];
  adapterAccessUnknown: boolean;
  adapterContracts: ModuleAdapterContract[];
  adapterError: ModuleAdapterApiErrorSummary | null;
  adapterMetadataUnavailable: boolean;
  adapterRegistryError: ModuleAdapterApiErrorSummary | null;
  executionProviderAccessItems: ExecutionProviderAccessState[];
  executionProviderAccessUnknown: boolean;
  executionProviderContracts: ExecutionProviderContract[];
  executionProviderError: ExecutionProviderApiErrorSummary | null;
  executionProviderMetadataUnavailable: boolean;
  executionProviderRegistryError: ExecutionProviderApiErrorSummary | null;
  isLoading: boolean;
  uiState: "loading" | "ready" | "degraded" | "fallback";
  isDegraded: boolean;
  isFallbackMode: boolean;
  moduleAccessUnknown: boolean;
  moduleError: ModuleApiErrorSummary | null;
  moduleItems: ModuleAccessState[];
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

type CapabilityAccessSnapshot = {
  adapterAccessItems: ModuleAdapterAccessState[];
  adapterAccessUnknown: boolean;
  adapterContracts: ModuleAdapterContract[];
  adapterError: ModuleAdapterApiErrorSummary | null;
  adapterMetadataUnavailable: boolean;
  adapterRegistryError: ModuleAdapterApiErrorSummary | null;
  executionProviderAccessItems: ExecutionProviderAccessState[];
  executionProviderAccessUnknown: boolean;
  executionProviderContracts: ExecutionProviderContract[];
  executionProviderError: ExecutionProviderApiErrorSummary | null;
  executionProviderMetadataUnavailable: boolean;
  executionProviderRegistryError: ExecutionProviderApiErrorSummary | null;
  moduleAccessUnknown: boolean;
  moduleError: ModuleApiErrorSummary | null;
  moduleItems: ModuleAccessState[];
};

const SAFE_ACCESS_SNAPSHOT: CapabilityAccessSnapshot = {
  adapterAccessItems: [],
  adapterAccessUnknown: true,
  adapterContracts: [],
  adapterError: null,
  adapterMetadataUnavailable: true,
  adapterRegistryError: null,
  executionProviderAccessItems: [],
  executionProviderAccessUnknown: true,
  executionProviderContracts: [],
  executionProviderError: null,
  executionProviderMetadataUnavailable: true,
  executionProviderRegistryError: null,
  moduleAccessUnknown: true,
  moduleError: null,
  moduleItems: [],
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
  adapterAccessItems: [],
  adapterAccessUnknown: true,
  adapterContracts: [],
  adapterError: null,
  adapterMetadataUnavailable: true,
  adapterRegistryError: null,
  executionProviderAccessItems: [],
  executionProviderAccessUnknown: true,
  executionProviderContracts: [],
  executionProviderError: null,
  executionProviderMetadataUnavailable: true,
  executionProviderRegistryError: null,
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
  moduleAccessUnknown: true,
  moduleError: null,
  moduleItems: [],
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
  const latestAuthRef = useRef({ status, user });
  latestAuthRef.current = { status, user };
  const mountedRef = useRef(false);
  const initStartedRef = useRef(false);
  const [accessSnapshot, setAccessSnapshot] =
    useState<CapabilityAccessSnapshot>(SAFE_ACCESS_SNAPSHOT);
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

  const applyFallbackState = useCallback(() => {
    if (!mountedRef.current) {
      return;
    }

    setAccessSnapshot(SAFE_ACCESS_SNAPSHOT);
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
  }, []);

  const loadCapabilityState = useCallback(async () => {
    const currentAuth = latestAuthRef.current;

    if (currentAuth.status !== "authenticated" || !currentAuth.user) {
      applyFallbackState();
      setIsLocalLoading(false);
      return;
    }

    setIsLocalLoading(true);
    try {
      const {
        adapterAccessResult,
        adapterRegistryResult,
        executionAccessResult,
        executionRegistryResult,
        moduleAccessResult,
        policiesResult,
        productionResult,
        readinessResult,
        registryResult,
      } = await getCapabilityBootstrap();

      if (!mountedRef.current) {
        return;
      }

      const hasLoadedState =
        registryResult.ok ||
        moduleAccessResult.ok ||
        adapterRegistryResult.ok ||
        adapterAccessResult.ok ||
        executionRegistryResult.ok ||
        executionAccessResult.ok ||
        readinessResult.ok ||
        productionResult.ok ||
        policiesResult.ok;

      setAccessSnapshot({
        adapterAccessItems: safeArray(adapterAccessResult?.data?.items),
        adapterAccessUnknown:
          adapterAccessResult?.adapter_access_unknown !== false,
        adapterContracts: safeArray(adapterRegistryResult?.data?.items),
        adapterError: adapterAccessResult?.error ?? null,
        adapterMetadataUnavailable: adapterRegistryResult?.ok !== true,
        adapterRegistryError: adapterRegistryResult?.error ?? null,
        executionProviderAccessItems: safeArray(
          executionAccessResult?.data?.items,
        ),
        executionProviderAccessUnknown:
          executionAccessResult?.provider_access_unknown !== false,
        executionProviderContracts: safeArray(
          executionRegistryResult?.data?.items,
        ),
        executionProviderError: executionAccessResult?.error ?? null,
        executionProviderMetadataUnavailable:
          executionRegistryResult?.ok !== true,
        executionProviderRegistryError: executionRegistryResult?.error ?? null,
        moduleAccessUnknown:
          moduleAccessResult?.module_access_unknown !== false,
        moduleError: moduleAccessResult?.error ?? null,
        moduleItems: safeArray(moduleAccessResult?.data?.items),
      });
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
      setIsFallbackMode(!hasLoadedState);
    } catch {
      applyFallbackState();
    } finally {
      if (mountedRef.current) {
        setIsLocalLoading(false);
      }
    }
  }, [applyFallbackState]);

  useEffect(() => {
    mountedRef.current = true;

    if (!initStartedRef.current) {
      initStartedRef.current = true;
      void loadCapabilityState();
    }

    return () => {
      mountedRef.current = false;
    };
  }, [loadCapabilityState]);

  const refresh = useCallback(async () => {
    await loadCapabilityState();
  }, [loadCapabilityState]);

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
          adapterAccessItems: safeArray(accessSnapshot.adapterAccessItems),
          adapterAccessUnknown: accessSnapshot.adapterAccessUnknown,
          adapterContracts: safeArray(accessSnapshot.adapterContracts),
          executionProviderAccessItems: safeArray(
            accessSnapshot.executionProviderAccessItems,
          ),
          executionProviderAccessUnknown:
            accessSnapshot.executionProviderAccessUnknown,
          executionProviderContracts: safeArray(
            accessSnapshot.executionProviderContracts,
          ),
          liveGate,
          moduleAccessItems: safeArray(accessSnapshot.moduleItems),
          moduleAccessUnknown: accessSnapshot.moduleAccessUnknown,
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
      accessSnapshot.adapterAccessItems,
      accessSnapshot.adapterAccessUnknown,
      accessSnapshot.adapterContracts,
      accessSnapshot.executionProviderAccessItems,
      accessSnapshot.executionProviderAccessUnknown,
      accessSnapshot.executionProviderContracts,
      accessSnapshot.moduleAccessUnknown,
      accessSnapshot.moduleItems,
      liveGate,
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
    isLocalLoading;
  const isDegraded =
    isFallbackMode ||
    registryUnavailable ||
    Boolean(registryError) ||
    Boolean(accessSnapshot.moduleError) ||
    Boolean(accessSnapshot.adapterError) ||
    Boolean(accessSnapshot.adapterRegistryError) ||
    Boolean(accessSnapshot.executionProviderError) ||
    Boolean(accessSnapshot.executionProviderRegistryError) ||
    Boolean(readinessError) ||
    Boolean(productionReadinessError) ||
    Boolean(policiesError) ||
    accessSnapshot.moduleAccessUnknown ||
    accessSnapshot.adapterAccessUnknown ||
    accessSnapshot.executionProviderAccessUnknown;
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
      adapterAccessItems: safeArray(accessSnapshot.adapterAccessItems),
      adapterAccessUnknown: accessSnapshot.adapterAccessUnknown,
      adapterContracts: safeArray(accessSnapshot.adapterContracts),
      adapterError: accessSnapshot.adapterError,
      adapterMetadataUnavailable: accessSnapshot.adapterMetadataUnavailable,
      adapterRegistryError: accessSnapshot.adapterRegistryError,
      executionProviderAccessItems: safeArray(
        accessSnapshot.executionProviderAccessItems,
      ),
      executionProviderAccessUnknown:
        accessSnapshot.executionProviderAccessUnknown,
      executionProviderContracts: safeArray(
        accessSnapshot.executionProviderContracts,
      ),
      executionProviderError: accessSnapshot.executionProviderError,
      executionProviderMetadataUnavailable:
        accessSnapshot.executionProviderMetadataUnavailable,
      executionProviderRegistryError:
        accessSnapshot.executionProviderRegistryError,
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
      moduleAccessUnknown: accessSnapshot.moduleAccessUnknown,
      moduleError: accessSnapshot.moduleError,
      moduleItems: safeArray(accessSnapshot.moduleItems),
      refresh,
      registryError,
      registryItems,
      registryUnavailable,
      uiState,
    }),
    [
      accessSnapshot.adapterAccessItems,
      accessSnapshot.adapterAccessUnknown,
      accessSnapshot.adapterContracts,
      accessSnapshot.adapterError,
      accessSnapshot.adapterMetadataUnavailable,
      accessSnapshot.adapterRegistryError,
      accessSnapshot.executionProviderAccessItems,
      accessSnapshot.executionProviderAccessUnknown,
      accessSnapshot.executionProviderContracts,
      accessSnapshot.executionProviderError,
      accessSnapshot.executionProviderMetadataUnavailable,
      accessSnapshot.executionProviderRegistryError,
      accessSnapshot.moduleAccessUnknown,
      accessSnapshot.moduleError,
      accessSnapshot.moduleItems,
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
