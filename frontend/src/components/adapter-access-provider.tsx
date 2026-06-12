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

import { useAuth } from "@/components/auth-provider";
import {
  listModuleAdapterRegistry,
  listMyModuleAdapters,
  type ModuleAdapterApiErrorSummary,
} from "@/lib/module-adapter-api";
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

type AdapterAccessContextValue = {
  adapters: ModuleAdapterContract[];
  accessItems: ModuleAdapterAccessState[];
  isLoading: boolean;
  adapterAccessUnknown: boolean;
  adapterMetadataUnavailable: boolean;
  error: ModuleAdapterApiErrorSummary | null;
  registryError: ModuleAdapterApiErrorSummary | null;
  refresh: () => Promise<void>;
};

const AdapterAccessContext =
  createContext<AdapterAccessContextValue | null>(null);

function isOwnerFullAccess(
  permissions: { is_owner_full_access?: boolean } | null | undefined,
) {
  return permissions?.is_owner_full_access === true;
}

export function AdapterAccessProvider({
  children,
}: {
  children: ReactNode;
}) {
  const { user, status } = useAuth();
  const [adapters, setAdapters] = useState<ModuleAdapterContract[]>([]);
  const [accessItems, setAccessItems] = useState<ModuleAdapterAccessState[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [adapterAccessUnknown, setAdapterAccessUnknown] = useState(true);
  const [adapterMetadataUnavailable, setAdapterMetadataUnavailable] =
    useState(true);
  const [error, setError] = useState<ModuleAdapterApiErrorSummary | null>(null);
  const [registryError, setRegistryError] =
    useState<ModuleAdapterApiErrorSummary | null>(null);

  const loadAdapterAccess = useCallback(async () => {
    if (status !== "authenticated" || !user) {
      setAdapters([]);
      setAccessItems([]);
      setError(null);
      setRegistryError(null);
      setIsLoading(false);
      setAdapterAccessUnknown(true);
      setAdapterMetadataUnavailable(true);
      return;
    }

    setIsLoading(true);
    const [registryResult, accessResult] = await Promise.all([
      listModuleAdapterRegistry(),
      listMyModuleAdapters(),
    ]);
    setAdapters(registryResult.data.items);
    setAccessItems(accessResult.data.items);
    setRegistryError(registryResult.error);
    setError(accessResult.error);
    setAdapterMetadataUnavailable(!registryResult.ok);
    setAdapterAccessUnknown(accessResult.adapter_access_unknown);
    setIsLoading(false);
  }, [status, user]);

  useEffect(() => {
    let active = true;

    async function refreshWhenActive() {
      if (!active) {
        return;
      }
      await loadAdapterAccess();
    }

    void refreshWhenActive();

    return () => {
      active = false;
    };
  }, [loadAdapterAccess]);

  const filteredAdapters = useMemo(() => {
    const owner = isOwnerFullAccess(user?.permissions);

    return adapters.filter((adapter) =>
      canExposeAdapterMetadata(
        adapter,
        findAdapterAccessState(adapter.adapter_key, accessItems),
        {
          adapterAccessUnknown,
          isOwnerFullAccess: owner,
        },
      ),
    );
  }, [accessItems, adapterAccessUnknown, adapters, user?.permissions]);

  const value = useMemo(
    () => ({
      accessItems,
      adapterAccessUnknown,
      adapterMetadataUnavailable,
      adapters: filteredAdapters,
      error,
      isLoading,
      refresh: loadAdapterAccess,
      registryError,
    }),
    [
      accessItems,
      adapterAccessUnknown,
      adapterMetadataUnavailable,
      error,
      filteredAdapters,
      isLoading,
      loadAdapterAccess,
      registryError,
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
    isExecutable: false,
    isHidden: isAdapterHidden(accessState),
    isLocked: isAdapterLocked(accessState),
    isUnavailable: isAdapterUnavailable(accessState),
    isVisible: isAdapterVisible(accessState),
  };
}
