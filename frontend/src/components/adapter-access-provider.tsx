"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import type {
  ExecutionProviderAccessState,
  ExecutionProviderContract,
} from "@/lib/execution-provider";
import type { ExecutionProviderApiErrorSummary } from "@/lib/execution-provider-api";
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
import type { ModuleAdapterApiErrorSummary } from "@/lib/module-adapter-api";

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
  isOwnerFullAccess: boolean;
  refresh: () => Promise<void>;
};

const AdapterAccessContext =
  createContext<AdapterAccessContextValue | null>(null);

const ADAPTER_ACCESS_MEMORY_CACHE_TTL_MS = 60_000;

type AdapterAccessMemoryCacheEntry = {
  expiresAt: number;
  value: ModuleAdapterContract[];
};

const adapterAccessMemoryCache = new Map<
  string,
  AdapterAccessMemoryCacheEntry
>();

function safeArray<T>(value: readonly T[] | null | undefined): T[] {
  return Array.isArray(value) ? [...value] : [];
}

function adapterAccessCacheKey({
  accessItems,
  adapterAccessUnknown,
  adapters,
  isOwnerFullAccess,
}: {
  adapters: readonly ModuleAdapterContract[];
  accessItems: readonly ModuleAdapterAccessState[];
  adapterAccessUnknown: boolean;
  isOwnerFullAccess: boolean;
}) {
  return JSON.stringify({
    access: accessItems.map((item) => [
      item.adapter_key,
      item.module_key,
      item.adapter_access_state,
      item.hidden,
      item.locked,
      item.unavailable,
    ]),
    adapterAccessUnknown,
    adapters: adapters.map((adapter) => [
      adapter.adapter_key,
      adapter.module_key,
      adapter.adapter_status,
    ]),
    isOwnerFullAccess,
  });
}

function getFilteredAdapters({
  accessItems,
  adapterAccessUnknown,
  adapters,
  isOwnerFullAccess,
}: {
  adapters: readonly ModuleAdapterContract[];
  accessItems: readonly ModuleAdapterAccessState[];
  adapterAccessUnknown: boolean;
  isOwnerFullAccess: boolean;
}) {
  const cacheKey = adapterAccessCacheKey({
    accessItems,
    adapterAccessUnknown,
    adapters,
    isOwnerFullAccess,
  });
  const cached = adapterAccessMemoryCache.get(cacheKey);
  const now = Date.now();

  if (cached && cached.expiresAt > now) {
    return [...cached.value];
  }

  const value = adapters.filter((adapter) =>
    canExposeAdapterMetadata(
      adapter,
      findAdapterAccessState(adapter.adapter_key, accessItems),
      {
        adapterAccessUnknown,
        isOwnerFullAccess,
      },
    ),
  );

  adapterAccessMemoryCache.set(cacheKey, {
    expiresAt: now + ADAPTER_ACCESS_MEMORY_CACHE_TTL_MS,
    value,
  });

  return [...value];
}

export function AdapterAccessProvider({
  children,
}: {
  children: ReactNode;
}) {
  const capabilityState = useFrontendCapabilityState();
  const {
    adapterAccessResult,
    adapterRegistryResult,
    executionAccessResult,
    executionRegistryResult,
  } = capabilityState;
  const adapters = safeArray(adapterRegistryResult?.data.items);
  const accessItems = safeArray(adapterAccessResult?.data.items);
  const executionProviders = safeArray(executionRegistryResult?.data.items);
  const executionProviderAccessItems = safeArray(
    executionAccessResult?.data.items,
  );
  const adapterAccessUnknown =
    adapterAccessResult?.adapter_access_unknown !== false;
  const isOwnerFullAccess =
    capabilityState.permissionSnapshot.is_owner_full_access === true ||
    adapterAccessResult?.data.is_owner_full_access === true ||
    executionAccessResult?.data.is_owner_full_access === true;

  const filteredAdapters = useMemo(
    () => {
      adapterAccessMemoryCache.clear();
      return getFilteredAdapters({
        accessItems,
        adapterAccessUnknown,
        adapters,
        isOwnerFullAccess,
      });
    },
    [
      accessItems,
      adapterAccessUnknown,
      adapters,
      capabilityState.refreshGeneration,
      isOwnerFullAccess,
    ],
  );

  const value = useMemo(
    () => ({
      accessItems,
      adapterAccessUnknown,
      adapterMetadataUnavailable: adapterRegistryResult?.ok !== true,
      adapters: filteredAdapters,
      error: adapterAccessResult?.error ?? null,
      executionProviderAccessItems,
      executionProviderAccessUnknown:
        executionAccessResult?.provider_access_unknown !== false,
      executionProviderError: executionAccessResult?.error ?? null,
      executionProviderMetadataUnavailable:
        executionRegistryResult?.ok !== true,
      executionProviderRegistryError: executionRegistryResult?.error ?? null,
      executionProviders,
      isOwnerFullAccess,
      isLoading: capabilityState.isLoading,
      refresh: capabilityState.refresh,
      registryError: adapterRegistryResult?.error ?? null,
    }),
    [
      accessItems,
      adapterAccessResult,
      adapterAccessUnknown,
      adapterRegistryResult,
      capabilityState.isLoading,
      capabilityState.refresh,
      executionAccessResult,
      executionProviderAccessItems,
      executionProviders,
      executionRegistryResult,
      filteredAdapters,
      isOwnerFullAccess,
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
    isHidden: !context.isOwnerFullAccess && isAdapterHidden(accessState),
    isLocked: !context.isOwnerFullAccess && isAdapterLocked(accessState),
    isOwnerFullAccess: context.isOwnerFullAccess,
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
    isHidden: !context.isOwnerFullAccess && isAdapterHidden(accessState),
    isLocked: !context.isOwnerFullAccess && isAdapterLocked(accessState),
    isOwnerFullAccess: context.isOwnerFullAccess,
    isUnavailable: isAdapterUnavailable(accessState),
    isVisible: isAdapterVisible(accessState),
  };
}
