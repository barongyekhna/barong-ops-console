"use client";

import {
  createContext,
  useContext,
  useMemo,
  type ReactNode,
} from "react";

import { useFrontendCapabilityState } from "@/components/capability-state-provider";
import type { ModuleApiErrorSummary } from "@/lib/module-registry-api";
import type { ModuleAccessState } from "@/lib/module-registry";

type ModuleAccessContextValue = {
  items: ModuleAccessState[];
  isLoading: boolean;
  moduleAccessUnknown: boolean;
  error: ModuleApiErrorSummary | null;
  refresh: () => Promise<void>;
};

const ModuleAccessContext = createContext<ModuleAccessContextValue | null>(
  null,
);

export function ModuleAccessProvider({
  children,
}: {
  children: ReactNode;
}) {
  const capabilityState = useFrontendCapabilityState();

  const value = useMemo(
    () => ({
      error: capabilityState.moduleError,
      isLoading: capabilityState.isLoading,
      items: capabilityState.moduleItems,
      moduleAccessUnknown: capabilityState.moduleAccessUnknown,
      refresh: capabilityState.refresh,
    }),
    [
      capabilityState.isLoading,
      capabilityState.moduleAccessUnknown,
      capabilityState.moduleError,
      capabilityState.moduleItems,
      capabilityState.refresh,
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
