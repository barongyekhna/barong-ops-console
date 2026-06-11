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
  listMyModules,
  type ModuleApiErrorSummary,
} from "@/lib/module-registry-api";
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
  const { user, status } = useAuth();
  const [items, setItems] = useState<ModuleAccessState[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [moduleAccessUnknown, setModuleAccessUnknown] = useState(true);
  const [error, setError] = useState<ModuleApiErrorSummary | null>(null);

  const loadModuleAccess = useCallback(async () => {
    if (status !== "authenticated" || !user) {
      setItems([]);
      setError(null);
      setIsLoading(false);
      setModuleAccessUnknown(true);
      return;
    }

    setIsLoading(true);
    const result = await listMyModules();
    setItems(result.data.items);
    setError(result.error);
    setModuleAccessUnknown(result.module_access_unknown);
    setIsLoading(false);
  }, [status, user]);

  useEffect(() => {
    let active = true;

    async function refreshWhenActive() {
      if (!active) {
        return;
      }
      await loadModuleAccess();
    }

    void refreshWhenActive();

    return () => {
      active = false;
    };
  }, [loadModuleAccess]);

  const value = useMemo(
    () => ({
      error,
      isLoading,
      items,
      moduleAccessUnknown,
      refresh: loadModuleAccess,
    }),
    [error, isLoading, items, loadModuleAccess, moduleAccessUnknown],
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
