"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";

import { useAuth } from "@/components/auth-provider";
import {
  buildFrontendUiCapabilityGraph,
  findCapabilityForPath,
  type FrontendCapabilityGraph,
  type ProductCapabilityItem,
} from "@/lib/frontend-capability-state";
import type {
  LiveGatePolicyRead,
  LiveGateRuntimeState,
  PreLiveValidationReport,
  ProductionReadinessReport,
} from "@/lib/live-gate";

type CapabilityUiState = "loading" | "ready" | "degraded" | "fallback";

type CapabilityStateContextValue = FrontendCapabilityGraph & {
  isLoading: boolean;
  uiState: CapabilityUiState;
  isDegraded: boolean;
  isFallbackMode: boolean;
  liveGate: LiveGateRuntimeState;
  liveGateErrors: {
    readiness: null;
    productionReadiness: null;
    policies: null;
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

function createContextValue({
  authStatus,
  role,
}: {
  authStatus: "checking" | "authenticated" | "unauthenticated" | "error";
  role: string;
}): CapabilityStateContextValue {
  const graph = buildFrontendUiCapabilityGraph({
    authStatus,
    role,
  });
  const liveGate = {
    ...graph.executionState,
    active_policy_count: 0,
    blocked_reason: graph.executionState.blocked_reason,
    source: graph.executionState.source,
  };
  const isLoading = authStatus === "checking";
  const isFallbackMode = authStatus !== "authenticated";
  const uiState: CapabilityUiState = isLoading
    ? "loading"
    : isFallbackMode
      ? "fallback"
      : "ready";

  return {
    ...graph,
    getCapabilityForPath: (pathname: string) =>
      findCapabilityForPath(pathname, graph.items),
    isDegraded: false,
    isFallbackMode,
    isLoading,
    liveGate,
    liveGateErrors: {
      policies: null,
      productionReadiness: null,
      readiness: null,
    },
    liveGateReports: {
      policies: [],
      productionReadiness: null,
      readiness: null,
    },
    refresh: async () => {},
    uiState,
  };
}

const SAFE_CONTEXT_VALUE = createContextValue({
  authStatus: "unauthenticated",
  role: "",
});

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
  const { status, user } = useAuth();
  const role = user?.role ?? "";

  const graph = useMemo(
    () =>
      buildFrontendUiCapabilityGraph({
        authStatus: status,
        role,
      }),
    [role, status],
  );
  const getCapabilityForPath = useCallback(
    (pathname: string) => findCapabilityForPath(pathname, graph.items),
    [graph.items],
  );
  const refresh = useCallback(async () => {}, []);
  const isLoading = status === "checking";
  const isFallbackMode = status !== "authenticated";
  const uiState: CapabilityUiState = isLoading
    ? "loading"
    : isFallbackMode
      ? "fallback"
      : "ready";
  const liveGate = useMemo(
    () => ({
      active_policy_count: 0,
      blocked_reason: graph.executionState.blocked_reason,
      canary_state: graph.executionState.canary_state,
      execution_mode: graph.executionState.execution_mode,
      live_gate_status: graph.executionState.live_gate_status,
      production_ready: graph.executionState.production_ready,
      readiness_passed: graph.executionState.readiness_passed,
      rollout_percentage: graph.executionState.rollout_percentage,
      source: graph.executionState.source,
    }),
    [graph.executionState],
  );

  const value = useMemo(
    () => ({
      ...graph,
      getCapabilityForPath,
      isDegraded: false,
      isFallbackMode,
      isLoading,
      liveGate,
      liveGateErrors: {
        policies: null,
        productionReadiness: null,
        readiness: null,
      },
      liveGateReports: {
        policies: [],
        productionReadiness: null,
        readiness: null,
      },
      refresh,
      uiState,
    }),
    [
      getCapabilityForPath,
      graph,
      isFallbackMode,
      isLoading,
      liveGate,
      refresh,
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
