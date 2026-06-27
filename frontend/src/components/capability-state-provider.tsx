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
import { ApiRequestAbortedError, isApiAbortError } from "@/lib/api";
import {
  getCapabilityBootstrap,
  type CapabilityBootstrapResult,
} from "@/lib/capability-bootstrap-api";
import { clearFrontendRequestCache } from "@/lib/request-cache";
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
import {
  createOwnerFullAccessPermissions,
  type FrontendPermissions,
} from "@/lib/permissions";

type CapabilityUiState = "loading" | "ready" | "degraded" | "fallback";

type CapabilityStateContextValue = FrontendCapabilityGraph & {
  bootstrap: CapabilityBootstrapResult | null;
  adapterAccessResult: CapabilityBootstrapResult["adapterAccessResult"] | null;
  adapterRegistryResult: CapabilityBootstrapResult["adapterRegistryResult"] | null;
  executionAccessResult: CapabilityBootstrapResult["executionAccessResult"] | null;
  executionRegistryResult: CapabilityBootstrapResult["executionRegistryResult"] | null;
  moduleAccessResult: CapabilityBootstrapResult["moduleAccessResult"] | null;
  moduleControlResult: CapabilityBootstrapResult["moduleControlResult"] | null;
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
  refreshGeneration: number;
};

const CapabilityStateContext =
  createContext<CapabilityStateContextValue | null>(null);

function authIdentityKey({
  status,
  user,
}: {
  status: string;
  user: {
    id?: number | string | null;
    role?: string | null;
    username?: string | null;
  } | null;
}) {
  if (status !== "authenticated") {
    return null;
  }

  if (!user) {
    return "token-authenticated";
  }

  return [user.id ?? "unknown", user.username ?? "", user.role ?? ""].join(
    ":",
  );
}

function permissionsFromBootstrap({
  bootstrap,
  isOwner,
}: {
  bootstrap: CapabilityBootstrapResult;
  isOwner: boolean;
}): FrontendPermissions {
  if (isOwner) {
    return createOwnerFullAccessPermissions();
  }

  const hasBackendOwnerFullAccess =
    bootstrap.moduleAccessResult.data.is_owner_full_access === true ||
    bootstrap.adapterAccessResult.data.is_owner_full_access === true ||
    bootstrap.executionAccessResult.data.is_owner_full_access === true;

  if (hasBackendOwnerFullAccess) {
    return createOwnerFullAccessPermissions();
  }

  return {
    assignments: [],
    is_owner_full_access: false,
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
  isOwner,
  role,
}: {
  bootstrap: CapabilityBootstrapResult;
  isOwner: boolean;
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
    permissions: permissionsFromBootstrap({ bootstrap, isOwner }),
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

function preservePreviousResult<
  T extends { ok: boolean; data: unknown; error: unknown },
>(previous: T | null | undefined, next: T): T {
  if (next.ok || !previous?.ok) {
    return next;
  }

  return {
    ...next,
    data: previous.data,
  };
}

function mergeCapabilityBootstrap(
  previous: CapabilityBootstrapResult | null,
  next: CapabilityBootstrapResult,
): CapabilityBootstrapResult {
  if (!previous) {
    return next;
  }

  return {
    adapterAccessResult: preservePreviousResult(
      previous.adapterAccessResult,
      next.adapterAccessResult,
    ),
    adapterRegistryResult: preservePreviousResult(
      previous.adapterRegistryResult,
      next.adapterRegistryResult,
    ),
    executionAccessResult: preservePreviousResult(
      previous.executionAccessResult,
      next.executionAccessResult,
    ),
    executionRegistryResult: preservePreviousResult(
      previous.executionRegistryResult,
      next.executionRegistryResult,
    ),
    moduleAccessResult: preservePreviousResult(
      previous.moduleAccessResult,
      next.moduleAccessResult,
    ),
    moduleControlResult: preservePreviousResult(
      previous.moduleControlResult,
      next.moduleControlResult,
    ),
    policiesResult: preservePreviousResult(
      previous.policiesResult,
      next.policiesResult,
    ),
    productionResult: preservePreviousResult(
      previous.productionResult,
      next.productionResult,
    ),
    readinessResult: preservePreviousResult(
      previous.readinessResult,
      next.readinessResult,
    ),
    registryResult: preservePreviousResult(
      previous.registryResult,
      next.registryResult,
    ),
  };
}

function createContextValue({
  authStatus,
  bootstrap,
  isLoading,
  loadError,
  refresh,
  refreshGeneration,
  isOwner,
  role,
}: {
  authStatus: "checking" | "authenticated" | "unauthenticated";
  bootstrap: CapabilityBootstrapResult | null;
  isLoading: boolean;
  loadError: string | null;
  refresh: () => Promise<void>;
  refreshGeneration: number;
  isOwner: boolean;
  role: string;
}): CapabilityStateContextValue {
  const graph =
    authStatus === "authenticated" && bootstrap
      ? graphFromBootstrap({ bootstrap, isOwner, role })
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
        bootstrap?.moduleControlResult.ok === false ||
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
    moduleControlResult: bootstrap?.moduleControlResult ?? null,
    refresh,
    refreshGeneration,
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
  refreshGeneration: 0,
  isOwner: false,
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
  const { isOwner, status, user } = useAuth();
  const role = user?.role ?? "";
  const mountedRef = useRef(false);
  const loadingAuthKeyRef = useRef<string | null>(null);
  const loadedAuthKeyRef = useRef<string | null>(null);
  const loadingPromiseRef = useRef<Promise<void> | null>(null);
  const latestAuthKeyRef = useRef<string | null>(null);
  const bootstrapAbortControllerRef = useRef<AbortController | null>(null);
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
  const [refreshGeneration, setRefreshGeneration] = useState(0);

  const abortCapabilityBootstrap = useCallback((message: string) => {
    const controller = bootstrapAbortControllerRef.current;
    bootstrapAbortControllerRef.current = null;

    if (controller && !controller.signal.aborted) {
      controller.abort(new ApiRequestAbortedError(message));
    }
  }, []);

  const loadCapabilityState = useCallback(
    async ({ force = false }: { force?: boolean } = {}) => {
      const currentAuthKey = authIdentityKey({ status, user });

      if (!currentAuthKey) {
        abortCapabilityBootstrap(
          "Capability bootstrap was aborted because auth is unavailable.",
        );
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

      if (force) {
        clearFrontendRequestCache({ includeInFlight: true });
        loadedAuthKeyRef.current = null;
        loadingPromiseRef.current = null;
        setBootstrap(null);
        setRefreshGeneration((value) => value + 1);
      }

      // alreadyLoading or alreadyLoaded, return cachedState
      setIsLoading(true);
      setLoadError(null);
      loadingAuthKeyRef.current = currentAuthKey;
      abortCapabilityBootstrap(
        "Capability bootstrap was replaced by a newer request.",
      );
      const controller = new AbortController();
      bootstrapAbortControllerRef.current = controller;

      const loadPromise = getCapabilityBootstrap({
        forceRefresh: force,
        signal: controller.signal,
      })
        .then((result) => {
          if (
            !mountedRef.current ||
            latestAuthKeyRef.current !== currentAuthKey ||
            controller.signal.aborted
          ) {
            return;
          }

          setBootstrap((current) =>
            force ? result : mergeCapabilityBootstrap(current, result),
          );
          loadedAuthKeyRef.current = currentAuthKey;
        })
        .catch((error) => {
          if (
            !mountedRef.current ||
            latestAuthKeyRef.current !== currentAuthKey ||
            controller.signal.aborted
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
            setLoadError("数据同步延迟，请重试。");
            return;
          }

          loadedAuthKeyRef.current = null;
          setLoadError("数据同步延迟，请重试。");
        })
        .finally(() => {
          if (bootstrapAbortControllerRef.current === controller) {
            bootstrapAbortControllerRef.current = null;
          }
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
    [abortCapabilityBootstrap, status, user],
  );

  useEffect(() => {
    mountedRef.current = true;
    void loadCapabilityState({ force: true });

    return () => {
      abortCapabilityBootstrap(
        "Capability bootstrap was aborted because the provider changed.",
      );
      mountedRef.current = false;
    };
  }, [
    abortCapabilityBootstrap,
    authKey,
    loadCapabilityState,
    loadRetryNonce,
  ]);

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
        refreshGeneration,
        isOwner,
        role,
      }),
    [
      bootstrap,
      isLoading,
      isOwner,
      loadError,
      refresh,
      refreshGeneration,
      role,
      status,
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
