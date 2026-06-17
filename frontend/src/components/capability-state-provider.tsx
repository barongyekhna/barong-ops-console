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
  policyError: "PRE20-Q live gate state has not loaded.",
  productionReadiness: null,
  productionReadinessError: "PRE20-Q production readiness has not loaded.",
  readiness: null,
  readinessError: "PRE20-Q readiness has not loaded.",
});

export function CapabilityStateProvider({
  children,
}: {
  children: ReactNode;
}) {
  const { status, user } = useAuth();
  const moduleAccess = useModuleAccess();
  const adapterAccess = useAdapterAccess();
  const [registryItems, setRegistryItems] = useState<ModuleManifest[]>([]);
  const [registryUnavailable, setRegistryUnavailable] = useState(true);
  const [registryError, setRegistryError] =
    useState<ModuleApiErrorSummary | null>(null);
  const [readiness, setReadiness] =
    useState<PreLiveValidationReport | null>(null);
  const [productionReadiness, setProductionReadiness] =
    useState<ProductionReadinessReport | null>(null);
  const [policies, setPolicies] = useState<LiveGatePolicyRead[]>([]);
  const [readinessError, setReadinessError] =
    useState<LiveGateApiErrorSummary | null>(null);
  const [productionReadinessError, setProductionReadinessError] =
    useState<LiveGateApiErrorSummary | null>(null);
  const [policiesError, setPoliciesError] =
    useState<LiveGateApiErrorSummary | null>(null);
  const [isLocalLoading, setIsLocalLoading] = useState(false);

  const loadCapabilityState = useCallback(async () => {
    if (status !== "authenticated" || !user) {
      setRegistryItems([]);
      setRegistryUnavailable(true);
      setRegistryError(null);
      setReadiness(null);
      setProductionReadiness(null);
      setPolicies([]);
      setReadinessError(null);
      setProductionReadinessError(null);
      setPoliciesError(null);
      setIsLocalLoading(false);
      return;
    }

    setIsLocalLoading(true);
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

    setRegistryItems(registryResult.data.items);
    setRegistryUnavailable(!registryResult.ok);
    setRegistryError(registryResult.error);
    setReadiness(readinessResult.ok ? readinessResult.data : null);
    setProductionReadiness(productionResult.ok ? productionResult.data : null);
    setPolicies(policiesResult.ok ? policiesResult.data : []);
    setReadinessError(readinessResult.error);
    setProductionReadinessError(productionResult.error);
    setPoliciesError(policiesResult.error);
    setIsLocalLoading(false);
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
    await Promise.all([
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
    () =>
      buildFrontendCapabilityGraph({
        adapterAccessItems: adapterAccess.accessItems,
        adapterAccessUnknown: adapterAccess.adapterAccessUnknown,
        adapterContracts: adapterAccess.adapters,
        executionProviderAccessItems:
          adapterAccess.executionProviderAccessItems,
        executionProviderAccessUnknown:
          adapterAccess.executionProviderAccessUnknown,
        executionProviderContracts: adapterAccess.executionProviders,
        liveGate,
        moduleAccessItems: moduleAccess.items,
        moduleAccessUnknown: moduleAccess.moduleAccessUnknown,
        permissions: user?.permissions,
        registryItems,
        registryUnavailable,
        role: user?.role ?? "",
      }),
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

  const value = useMemo(
    () => ({
      ...graph,
      getCapabilityForPath,
      isLoading:
        isLocalLoading || moduleAccess.isLoading || adapterAccess.isLoading,
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
    }),
    [
      adapterAccess.isLoading,
      getCapabilityForPath,
      graph,
      isLocalLoading,
      liveGate,
      moduleAccess.isLoading,
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
  if (!context) {
    throw new Error(
      "useFrontendCapabilityState must be used inside CapabilityStateProvider.",
    );
  }

  return context;
}
