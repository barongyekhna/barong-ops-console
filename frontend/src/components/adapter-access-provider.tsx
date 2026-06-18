"use client";

import {
  createContext,
  useContext,
  useMemo,
  type ReactNode,
} from "react";

import { useAuth } from "@/components/auth-provider";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import type { ModuleAdapterApiErrorSummary } from "@/lib/module-adapter-api";
import type { ExecutionProviderApiErrorSummary } from "@/lib/execution-provider-api";
import type {
  ExecutionProviderAccessState,
  ExecutionProviderContract,
} from "@/lib/execution-provider";
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
  const { user } = useAuth();
  const capabilityState = useFrontendCapabilityState();

  const filteredAdapters = useMemo(() => {
    const owner = isOwnerFullAccess(user?.permissions);

    return capabilityState.adapterContracts.filter((adapter) =>
      canExposeAdapterMetadata(
        adapter,
        findAdapterAccessState(
          adapter.adapter_key,
          capabilityState.adapterAccessItems,
        ),
        {
          adapterAccessUnknown: capabilityState.adapterAccessUnknown,
          isOwnerFullAccess: owner,
        },
      ),
    );
  }, [
    capabilityState.adapterAccessItems,
    capabilityState.adapterAccessUnknown,
    capabilityState.adapterContracts,
    user?.permissions,
  ]);

  const value = useMemo(
    () => ({
      accessItems: capabilityState.adapterAccessItems,
      adapterAccessUnknown: capabilityState.adapterAccessUnknown,
      adapterMetadataUnavailable: capabilityState.adapterMetadataUnavailable,
      adapters: filteredAdapters,
      error: capabilityState.adapterError,
      executionProviderAccessItems:
        capabilityState.executionProviderAccessItems,
      executionProviderAccessUnknown:
        capabilityState.executionProviderAccessUnknown,
      executionProviderError: capabilityState.executionProviderError,
      executionProviderMetadataUnavailable:
        capabilityState.executionProviderMetadataUnavailable,
      executionProviderRegistryError:
        capabilityState.executionProviderRegistryError,
      executionProviders: capabilityState.executionProviderContracts,
      isLoading: capabilityState.isLoading,
      refresh: capabilityState.refresh,
      registryError: capabilityState.adapterRegistryError,
    }),
    [
      capabilityState.adapterAccessItems,
      capabilityState.adapterAccessUnknown,
      capabilityState.adapterError,
      capabilityState.adapterMetadataUnavailable,
      capabilityState.adapterRegistryError,
      capabilityState.executionProviderAccessItems,
      capabilityState.executionProviderAccessUnknown,
      capabilityState.executionProviderContracts,
      capabilityState.executionProviderError,
      capabilityState.executionProviderMetadataUnavailable,
      capabilityState.executionProviderRegistryError,
      capabilityState.isLoading,
      capabilityState.refresh,
      filteredAdapters,
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
