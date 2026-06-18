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
import type {
  ExecutionProviderAccessState,
  ExecutionProviderContract,
} from "@/lib/execution-provider";
import {
  getExecutionProviderRegistry,
  getMyExecutionProviders,
  type ExecutionProviderApiErrorSummary,
} from "@/lib/execution-provider-api";
import {
  canExposeAdapterMetadata,
  findAdapterAccessState,
  findAdapterContract,
  findAdapterContractByModuleKey,
  isAdapterHidden,
  isAdapterLocked,
  isAdapterUnavailable,
  isAdapterVisible,
  type ModuleAdapterAccessState,
  type ModuleAdapterContract,
} from "@/lib/module-adapter";
import {
  listModuleAdapterRegistry,
  listMyModuleAdapters,
  type ModuleAdapterApiErrorSummary,
} from "@/lib/module-adapter-api";

type AdapterAccessContextValue = {
  adapters: ModuleAdapterContract[];
  accessItems: ModuleAdapterAccessState[];
  executionProviders: ExecutionProviderContract[];
  executionProviderAccessItems: ExecutionProviderAccessState[];
  isLoading: boolean;
  adapterAccessUnknown: boolean;
  adapterMetadataUnavailable: boolean;
  executionProviderAccessUnknown: boolean;
  executionProviderMetadataUnavailable: boolean;
  error: ModuleAdapterApiErrorSummary | null;
  registryError: ModuleAdapterApiErrorSummary | null;
  executionProviderError: ExecutionProviderApiErrorSummary | null;
  executionProviderRegistryError: ExecutionProviderApiErrorSummary | null;
  refresh: () => Promise<void>;
};

const AdapterAccessContext =
  createContext<AdapterAccessContextValue | null>(null);

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

function safeArray<T>(value: readonly T[] | null | undefined): T[] {
  return Array.isArray(value) ? [...value] : [];
}

export function AdapterAccessProvider({
  children,
}: {
  children: ReactNode;
}) {
  const { status, user } = useAuth();
  const mountedRef = useRef(false);
  const loadingKeyRef = useRef<string | null>(null);
  const loadedKeyRef = useRef<string | null>(null);
  const loadingPromiseRef = useRef<Promise<void> | null>(null);
  const authKey = useMemo(
    () => authIdentityKey({ status, user }),
    [status, user?.id, user?.role, user?.username],
  );
  const latestAuthKeyRef = useRef<string | null>(authKey);
  latestAuthKeyRef.current = authKey;
  const [adapters, setAdapters] = useState<ModuleAdapterContract[]>([]);
  const [accessItems, setAccessItems] = useState<ModuleAdapterAccessState[]>(
    [],
  );
  const [executionProviders, setExecutionProviders] = useState<
    ExecutionProviderContract[]
  >([]);
  const [executionProviderAccessItems, setExecutionProviderAccessItems] =
    useState<ExecutionProviderAccessState[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [adapterAccessUnknown, setAdapterAccessUnknown] = useState(true);
  const [adapterMetadataUnavailable, setAdapterMetadataUnavailable] =
    useState(true);
  const [
    executionProviderAccessUnknown,
    setExecutionProviderAccessUnknown,
  ] = useState(true);
  const [
    executionProviderMetadataUnavailable,
    setExecutionProviderMetadataUnavailable,
  ] = useState(true);
  const [error, setError] =
    useState<ModuleAdapterApiErrorSummary | null>(null);
  const [registryError, setRegistryError] =
    useState<ModuleAdapterApiErrorSummary | null>(null);
  const [executionProviderError, setExecutionProviderError] =
    useState<ExecutionProviderApiErrorSummary | null>(null);
  const [
    executionProviderRegistryError,
    setExecutionProviderRegistryError,
  ] = useState<ExecutionProviderApiErrorSummary | null>(null);
  const [isOwnerFullAccess, setIsOwnerFullAccess] = useState(false);

  const applyFallbackState = useCallback(() => {
    if (!mountedRef.current) {
      return;
    }

    setAdapters([]);
    setAccessItems([]);
    setExecutionProviders([]);
    setExecutionProviderAccessItems([]);
    setAdapterAccessUnknown(true);
    setAdapterMetadataUnavailable(true);
    setExecutionProviderAccessUnknown(true);
    setExecutionProviderMetadataUnavailable(true);
    setError(null);
    setRegistryError(null);
    setExecutionProviderError(null);
    setExecutionProviderRegistryError(null);
    setIsOwnerFullAccess(false);
  }, []);

  const loadAdapterMetadata = useCallback(
    async ({ force = false }: { force?: boolean } = {}) => {
      const currentAuthKey = authIdentityKey({ status, user });

      if (!currentAuthKey) {
        applyFallbackState();
        setIsLoading(false);
        return;
      }

      if (
        !force &&
        loadingPromiseRef.current &&
        loadingKeyRef.current === currentAuthKey
      ) {
        return loadingPromiseRef.current;
      }

      if (!force && loadedKeyRef.current === currentAuthKey) {
        return;
      }

      setIsLoading(true);
      loadingKeyRef.current = currentAuthKey;

      const loadPromise = (async () => {
        const [
          adapterRegistryResult,
          adapterAccessResult,
          executionRegistryResult,
          executionAccessResult,
        ] = await Promise.all([
          listModuleAdapterRegistry(),
          listMyModuleAdapters(),
          getExecutionProviderRegistry(),
          getMyExecutionProviders(),
        ]);

        if (
          !mountedRef.current ||
          latestAuthKeyRef.current !== currentAuthKey
        ) {
          return;
        }

        setAdapters(safeArray(adapterRegistryResult.data.items));
        setAdapterMetadataUnavailable(adapterRegistryResult.ok !== true);
        setRegistryError(adapterRegistryResult.error);
        setAccessItems(safeArray(adapterAccessResult.data.items));
        setAdapterAccessUnknown(
          adapterAccessResult.adapter_access_unknown !== false,
        );
        setError(adapterAccessResult.error);
        setExecutionProviders(safeArray(executionRegistryResult.data.items));
        setExecutionProviderMetadataUnavailable(
          executionRegistryResult.ok !== true,
        );
        setExecutionProviderRegistryError(executionRegistryResult.error);
        setExecutionProviderAccessItems(
          safeArray(executionAccessResult.data.items),
        );
        setExecutionProviderAccessUnknown(
          executionAccessResult.provider_access_unknown !== false,
        );
        setExecutionProviderError(executionAccessResult.error);
        setIsOwnerFullAccess(
          adapterAccessResult.data.is_owner_full_access === true ||
            executionAccessResult.data.is_owner_full_access === true,
        );
        loadedKeyRef.current = currentAuthKey;
      })().finally(() => {
        if (loadingKeyRef.current === currentAuthKey) {
          loadingKeyRef.current = null;
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
    [applyFallbackState, status, user],
  );

  useEffect(() => {
    mountedRef.current = true;

    if (!authKey) {
      loadedKeyRef.current = null;
      loadingKeyRef.current = null;
      loadingPromiseRef.current = null;
      applyFallbackState();
      setIsLoading(false);
    } else {
      void loadAdapterMetadata();
    }

    return () => {
      mountedRef.current = false;
    };
  }, [applyFallbackState, authKey, loadAdapterMetadata]);

  const refresh = useCallback(async () => {
    await loadAdapterMetadata({ force: true });
  }, [loadAdapterMetadata]);

  const filteredAdapters = useMemo(
    () =>
      adapters.filter((adapter) =>
        canExposeAdapterMetadata(
          adapter,
          findAdapterAccessState(adapter.adapter_key, accessItems),
          {
            adapterAccessUnknown,
            isOwnerFullAccess,
          },
        ),
      ),
    [accessItems, adapterAccessUnknown, adapters, isOwnerFullAccess],
  );

  const value = useMemo(
    () => ({
      accessItems,
      adapterAccessUnknown,
      adapterMetadataUnavailable,
      adapters: filteredAdapters,
      error,
      executionProviderAccessItems,
      executionProviderAccessUnknown,
      executionProviderError,
      executionProviderMetadataUnavailable,
      executionProviderRegistryError,
      executionProviders,
      isLoading: status === "checking" || isLoading,
      refresh,
      registryError,
    }),
    [
      accessItems,
      adapterAccessUnknown,
      adapterMetadataUnavailable,
      error,
      executionProviderAccessItems,
      executionProviderAccessUnknown,
      executionProviderError,
      executionProviderMetadataUnavailable,
      executionProviderRegistryError,
      executionProviders,
      filteredAdapters,
      isLoading,
      refresh,
      registryError,
      status,
    ],
  );

  return (
    <AdapterAccessContext.Provider value={value}>
      {children}
    </AdapterAccessContext.Provider>
  );
}

export function useAdapterAccess() {
  const context = useContext(AdapterAccessContext);
  if (!context) {
    throw new Error(
      "useAdapterAccess must be used inside AdapterAccessProvider.",
    );
  }

  return context;
}

export function useAdapterRegistry() {
  const context = useAdapterAccess();

  return {
    adapterAccessUnknown: context.adapterAccessUnknown,
    adapterMetadataUnavailable: context.adapterMetadataUnavailable,
    error: context.registryError,
    executionProviderAccessUnknown: context.executionProviderAccessUnknown,
    executionProviderMetadataUnavailable:
      context.executionProviderMetadataUnavailable,
    executionProviderRegistryError: context.executionProviderRegistryError,
    executionProviders: context.executionProviders,
    isLoading: context.isLoading,
    items: context.adapters,
    refresh: context.refresh,
  };
}

export function useAdapterState(adapterKey: string | null | undefined) {
  const context = useAdapterAccess();
  const adapter = adapterKey
    ? findAdapterContract(adapterKey, context.adapters)
    : null;
  const accessState = adapterKey
    ? findAdapterAccessState(adapterKey, context.accessItems)
    : null;

  return {
    accessState,
    adapter,
    adapterAccessUnknown:
      context.adapterAccessUnknown || Boolean(adapterKey && !accessState),
    adapterMetadataUnavailable:
      context.adapterMetadataUnavailable || Boolean(adapterKey && !adapter),
    executionProviderAccessItems: context.executionProviderAccessItems,
    executionProviderAccessUnknown: context.executionProviderAccessUnknown,
    executionProviderMetadataUnavailable:
      context.executionProviderMetadataUnavailable,
    executionProviders: context.executionProviders,
    isExecutable: false,
    isHidden: isAdapterHidden(accessState),
    isLocked: isAdapterLocked(accessState),
    isUnavailable: isAdapterUnavailable(accessState),
    isVisible: isAdapterVisible(accessState),
  };
}

export function useAdapterStateForModule(moduleKey: string | null | undefined) {
  const context = useAdapterAccess();
  const adapter = moduleKey
    ? findAdapterContractByModuleKey(moduleKey, context.adapters)
    : null;
  const accessState = adapter
    ? findAdapterAccessState(adapter.adapter_key, context.accessItems)
    : null;

  return {
    accessState,
    adapter,
    adapterAccessUnknown:
      context.adapterAccessUnknown || Boolean(adapter && !accessState),
    adapterMetadataUnavailable:
      context.adapterMetadataUnavailable || Boolean(moduleKey && !adapter),
    executionProviderAccessItems: context.executionProviderAccessItems,
    executionProviderAccessUnknown: context.executionProviderAccessUnknown,
    executionProviderMetadataUnavailable:
      context.executionProviderMetadataUnavailable,
    executionProviders: context.executionProviders,
    isExecutable: false,
    isHidden: isAdapterHidden(accessState),
    isLocked: isAdapterLocked(accessState),
    isUnavailable: isAdapterUnavailable(accessState),
    isVisible: isAdapterVisible(accessState),
  };
}
