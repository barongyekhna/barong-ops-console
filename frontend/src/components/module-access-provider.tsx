"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import type { ModuleApiErrorSummary } from "@/lib/module-registry-api";
import type {
  ModuleAccessState,
  ModuleManifest,
} from "@/lib/module-registry";

type ModuleAccessContextValue = {
  items: ModuleAccessState[];
  registryItems: ModuleManifest[];
  isLoading: boolean;
  moduleAccessUnknown: boolean;
  registryUnavailable: boolean;
  error: ModuleApiErrorSummary | null;
  registryError: ModuleApiErrorSummary | null;
  refresh: () => Promise<void>;
};

const ModuleAccessContext = createContext<ModuleAccessContextValue | null>(
  null,
);

const SAFE_CONTEXT_VALUE: ModuleAccessContextValue = {
  error: null,
  isLoading: false,
  items: [],
  moduleAccessUnknown: true,
  refresh: async () => {},
  registryError: null,
  registryItems: [],
  registryUnavailable: true,
};

function safeArray<T>(value: readonly T[] | null | undefined): T[] {
  return Array.isArray(value) ? [...value] : [];
}

export function ModuleAccessProvider({
  children,
}: {
  children: ReactNode;
}) {
  const capabilityState = useFrontendCapabilityState();
  const { moduleAccessResult, registryResult } = capabilityState;

  const value = useMemo(
    () => ({
      error: moduleAccessResult?.error ?? null,
      isLoading: capabilityState.isLoading,
      items: safeArray(moduleAccessResult?.data.items),
      moduleAccessUnknown:
        moduleAccessResult?.module_access_unknown !== false,
      refresh: capabilityState.refresh,
      registryError: registryResult?.error ?? null,
      registryItems: safeArray(registryResult?.data.items),
      registryUnavailable: registryResult?.ok !== true,
    }),
    [
      capabilityState.isLoading,
      capabilityState.refresh,
      moduleAccessResult,
      registryResult,
    ],
  );

  return (
    <ModuleAccessContext.Provider value={value}>
      {children}
    </ModuleAccessContext.Provider>
  );
}

export function useModuleAccess() {
  const context = useContext(ModuleAccessContext);
  if (!context) {
    throw new Error(
      "useModuleAccess must be used inside ModuleAccessProvider.",
    );
  }

  return context;
}

export function useSafeModuleAccess() {
  return useContext(ModuleAccessContext) ?? SAFE_CONTEXT_VALUE;
}
