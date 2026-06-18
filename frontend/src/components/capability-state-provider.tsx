"use client";

import { usePathname } from "next/navigation";
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
import { isApiAbortError } from "@/lib/api";
import {
  getCapabilityBootstrap,
  type CapabilityBootstrapResult,
} from "@/lib/capability-bootstrap-api";
import {
  buildFrontendCapabilityGraph,
  buildFrontendUiCapabilityGraph,
  findCapabilityForPath,
  type FrontendCapabilityGraph,
  type ProductCapabilityItem,
} from "@/lib/frontend-capability-state";
import {
  deriveLiveGateRuntimeState,
  type LiveGatePolicyRead,
  type LiveGateRuntimeState,
  type PreLiveValidationReport,
  type ProductionReadinessReport,
} from "@/lib/live-gate";
import type { FrontendPermissions } from "@/lib/permissions";

type CapabilityUiState = "loading" | "ready" | "degraded" | "fallback";

type CapabilityStateContextValue = FrontendCapabilityGraph & {
  bootstrap: CapabilityBootstrapResult | null;
  adapterAccessResult: CapabilityBootstrapResult["adapterAccessResult"] | null;
  adapterRegistryResult: CapabilityBootstrapResult["adapterRegistryResult"] | null;
  executionAccessResult: CapabilityBootstrapResult["executionAccessResult"] | null;
  executionRegistryResult: CapabilityBootstrapResult["executionRegistryResult"] | null;
  moduleAccessResult: CapabilityBootstrapResult["moduleAccessResult"] | null;
  registryResult: CapabilityBootstrapResult["registryResult"] | null;
  isLoading: boolean;
  uiState: CapabilityUiState;
  isDegraded: boolean;
  isFallbackMode: boolean;
  liveGate: LiveGateRuntimeState;
  liveGateErrors: {
    readiness: string | null;
    productionReadiness: string | null;
    policies: string | null;
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

function authIdentityKey({
  status,
  user,
}: {
  status: string;
  user: { id?: number | string | null; role?: string | null; username?: string | null } | null;
}) {
  if (status !== "authenticated" || !user) {
    return null;
  }

  return [user.id ?? "unknown", user.username ?? "", user.role ?? ""].join(":");
}

function ownerPermissionsFromBootstrap({
  bootstrap,
}: {
  bootstrap: CapabilityBootstrapResult;
}): FrontendPermissions {
  return {
    assignments: [],
    is_owner_full_access:
      bootstrap.moduleAccessResult.data.is_owner_full_access === true ||
      bootstrap.adapterAccessResult.data.is_owner_full_access === true ||
      bootstrap.executionAccessResult.data.is_owner_full_access === true,
    permission_keys: [],
    scope_summary: [],
  };
}

function liveGateFromBootstrap(
  bootstrap: CapabilityBootstrapResult,
): LiveGateRuntimeState {
  return deriveLiveGateRuntimeState({
    policies: bootstrap.policiesResult.data,
    policyError: bootstrap.policiesResult.error?.message,
    productionReadiness: bootstrap.productionResult.data,
    productionReadinessError: bootstrap.productionResult.error?.message,
    readiness: bootstrap.readinessResult.data,
    readinessError: bootstrap.readinessResult.error?.message,
  });
}

function graphFromBootstrap({
  bootstrap,
  role,
}: {
  bootstrap: CapabilityBootstrapResult;
  role: string;
}) {
  return buildFrontendCapabilityGraph({
    adapterAccessItems: bootstrap.adapterAccessResult.data.items,
    adapterAccessUnknown:
      bootstrap.adapterAccessResult.adapter_access_unknown !== false,
    adapterContracts: bootstrap.adapterRegistryResult.data.items,
    executionProviderAccessItems: bootstrap.executionAccessResult.data.items,
    executionProviderAccessUnknown:
      bootstrap.executionAccessResult.provider_access_unknown !== false,
    executionProviderContracts: bootstrap.executionRegistryResult.data.items,
    liveGate: liveGateFromBootstrap(bootstrap),
    moduleAccessItems: bootstrap.moduleAccessResult.data.items,
    moduleAccessUnknown:
      bootstrap.moduleAccessResult.module_access_unknown !== false,
    permissions: ownerPermissionsFromBootstrap({ bootstrap }),
    registryItems: bootstrap.registryResult.data.items,
    registryUnavailable: bootstrap.registryResult.ok !== true,
    role: bootstrap.moduleAccessResult.data.role || role,
  });
}

function isRouteChangeAbort(error: unknown) {
  return (
    error instanceof Error &&
    error.message.toLowerCase().includes("route changed")
  );
}

function createContextValue({
  authStatus,
  bootstrap,
  isLoading,
  loadError,
  refresh,
  role,
}: {
  authStatus: "checking" | "authenticated" | "unauthenticated";
  bootstrap: CapabilityBootstrapResult | null;
  isLoading: boolean;
  loadError: string | null;
  refresh: () => Promise<void>;
  role: string;
}): CapabilityStateContextValue {
  const graph =
    authStatus === "authenticated" && bootstrap
      ? graphFromBootstrap({ bootstrap, role })
      : buildFrontendUiCapabilityGraph({
          authStatus,
          role,
        });
  const liveGate = bootstrap
    ? liveGateFromBootstrap(bootstrap)
    : {
        ...graph.executionState,
        active_policy_count: 0,
        blocked_reason: graph.executionState.blocked_reason,
        source: graph.executionState.source,
      };
  const isFallbackMode = authStatus !== "authenticated";
  const isDegraded =
    authStatus === "authenticated" &&
    Boolean(
      loadError ||
        bootstrap?.registryResult.ok === false ||
        bootstrap?.moduleAccessResult.ok === false ||
        bootstrap?.adapterRegistryResult.ok === false ||
        bootstrap?.adapterAccessResult.ok === false ||
        bootstrap?.executionRegistryResult.ok === false ||
        bootstrap?.executionAccessResult.ok === false ||
        bootstrap?.readinessResult.ok === false ||
        bootstrap?.productionResult.ok === false ||
        bootstrap?.policiesResult.ok === false,
    );
  const uiState: CapabilityUiState = isLoading
    ? "loading"
    : isFallbackMode
      ? "fallback"
      : isDegraded
        ? "degraded"
        : "ready";

  return {
    ...graph,
    adapterAccessResult: bootstrap?.adapterAccessResult ?? null,
    adapterRegistryResult: bootstrap?.adapterRegistryResult ?? null,
    bootstrap,
    executionAccessResult: bootstrap?.executionAccessResult ?? null,
    executionRegistryResult: bootstrap?.executionRegistryResult ?? null,
    getCapabilityForPath: (pathname: string) =>
      findCapabilityForPath(pathname, graph.items),
    isDegraded,
    isFallbackMode,
    isLoading,
    liveGate,
    liveGateErrors: {
      policies: bootstrap?.policiesResult.error?.message ?? null,
      productionReadiness:
        bootstrap?.productionResult.error?.message ?? null,
      readiness: bootstrap?.readinessResult.error?.message ?? loadError,
    },
    liveGateReports: {
      policies: bootstrap?.policiesResult.data ?? [],
      productionReadiness: bootstrap?.productionResult.data ?? null,
      readiness: bootstrap?.readinessResult.data ?? null,
    },
    moduleAccessResult: bootstrap?.moduleAccessResult ?? null,
    refresh,
    registryResult: bootstrap?.registryResult ?? null,
    uiState,
  };
}

const SAFE_CONTEXT_VALUE = createContextValue({
  authStatus: "unauthenticated",
  bootstrap: null,
  isLoading: false,
  loadError: null,
  refresh: async () => {},
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
  const pathname = usePathname();
  const { status, user } = useAuth();
  const role = user?.role ?? "";
  const mountedRef = useRef(false);
  const loadingAuthKeyRef = useRef<string | null>(null);
  const loadedAuthKeyRef = useRef<string | null>(null);
  const loadingPromiseRef = useRef<Promise<void> | null>(null);
  const latestAuthKeyRef = useRef<string | null>(null);
  const authKey = useMemo(
    () => authIdentityKey({ status, user }),
    [status, user?.id, user?.role, user?.username],
  );
  latestAuthKeyRef.current = authKey;

  const [bootstrap, setBootstrap] = useState<CapabilityBootstrapResult | null>(
    null,
  );
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadRetryNonce, setLoadRetryNonce] = useState(0);

  const loadCapabilityState = useCallback(
    async ({ force = false }: { force?: boolean } = {}) => {
      const currentAuthKey = authIdentityKey({ status, user });

      if (!currentAuthKey) {
        loadedAuthKeyRef.current = null;
        loadingAuthKeyRef.current = null;
        loadingPromiseRef.current = null;
        setBootstrap(null);
        setLoadError(null);
        setIsLoading(false);
        return;
      }

      if (
        !force &&
        loadingPromiseRef.current &&
        loadingAuthKeyRef.current === currentAuthKey
      ) {
        return loadingPromiseRef.current;
      }

      if (!force && loadedAuthKeyRef.current === currentAuthKey) {
        return;
      }

      // alreadyLoading or alreadyLoaded, return cachedState
      setIsLoading(true);
      setLoadError(null);
      loadingAuthKeyRef.current = currentAuthKey;

      const loadPromise = getCapabilityBootstrap()
        .then((result) => {
          if (
            !mountedRef.current ||
            latestAuthKeyRef.current !== currentAuthKey
          ) {
            return;
          }

          setBootstrap(result);
          loadedAuthKeyRef.current = currentAuthKey;
        })
        .catch((error) => {
          if (
            !mountedRef.current ||
            latestAuthKeyRef.current !== currentAuthKey
          ) {
            return;
          }

          if (isRouteChangeAbort(error)) {
            loadedAuthKeyRef.current = null;
            setLoadRetryNonce((value) => value + 1);
            return;
          }

          if (isApiAbortError(error)) {
            loadedAuthKeyRef.current = null;
            setBootstrap(null);
            setLoadError(
              error instanceof Error
                ? error.message
                : "Capability bootstrap was aborted.",
            );
            return;
          }

          loadedAuthKeyRef.current = null;
          setBootstrap(null);
          setLoadError(
            error instanceof Error
              ? error.message
              : "Capability bootstrap failed.",
          );
        })
        .finally(() => {
          if (loadingAuthKeyRef.current === currentAuthKey) {
            loadingAuthKeyRef.current = null;
            loadingPromiseRef.current = null;
          }
          if (
            mountedRef.current &&
            latestAuthKeyRef.current === currentAuthKey
          ) {
            setIsLoading(false);
          }
        });

      loadingPromiseRef.current = loadPromise;
      return loadPromise;
    },
    [status, user],
  );

  useEffect(() => {
    mountedRef.current = true;
    void loadCapabilityState();

    return () => {
      mountedRef.current = false;
    };
  }, [authKey, loadCapabilityState, loadRetryNonce, pathname]);

  const refresh = useCallback(async () => {
    await loadCapabilityState({ force: true });
  }, [loadCapabilityState]);

  const value = useMemo(
    () =>
      createContextValue({
        authStatus: status,
        bootstrap,
        isLoading,
        loadError,
        refresh,
        role,
      }),
    [bootstrap, isLoading, loadError, refresh, role, status],
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
