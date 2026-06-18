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
import {
  listModuleRegistry,
  listMyModules,
  type ModuleApiErrorSummary,
} from "@/lib/module-registry-api";
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

export function ModuleAccessProvider({
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
  const [items, setItems] = useState<ModuleAccessState[]>([]);
  const [registryItems, setRegistryItems] = useState<ModuleManifest[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [moduleAccessUnknown, setModuleAccessUnknown] = useState(true);
  const [registryUnavailable, setRegistryUnavailable] = useState(true);
  const [error, setError] = useState<ModuleApiErrorSummary | null>(null);
  const [registryError, setRegistryError] =
    useState<ModuleApiErrorSummary | null>(null);

  const applyFallbackState = useCallback(() => {
    if (!mountedRef.current) {
      return;
    }

    setItems([]);
    setRegistryItems([]);
    setModuleAccessUnknown(true);
    setRegistryUnavailable(true);
    setError(null);
    setRegistryError(null);
  }, []);

  const loadModuleMetadata = useCallback(
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
        const [registryResult, moduleAccessResult] = await Promise.all([
          listModuleRegistry(),
          listMyModules(),
        ]);

        if (
          !mountedRef.current ||
          latestAuthKeyRef.current !== currentAuthKey
        ) {
          return;
        }

        setRegistryItems(safeArray(registryResult.data.items));
        setRegistryUnavailable(registryResult.ok !== true);
        setRegistryError(registryResult.error);
        setItems(safeArray(moduleAccessResult.data.items));
        setModuleAccessUnknown(
          moduleAccessResult.module_access_unknown !== false,
        );
        setError(moduleAccessResult.error);
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
      void loadModuleMetadata();
    }

    return () => {
      mountedRef.current = false;
    };
  }, [applyFallbackState, authKey, loadModuleMetadata]);

  const refresh = useCallback(async () => {
    await loadModuleMetadata({ force: true });
  }, [loadModuleMetadata]);

  const value = useMemo(
    () => ({
      error,
      isLoading: status === "checking" || isLoading,
      items,
      moduleAccessUnknown,
      refresh,
      registryError,
      registryItems,
      registryUnavailable,
    }),
    [
      error,
      isLoading,
      items,
      moduleAccessUnknown,
      refresh,
      registryError,
      registryItems,
      registryUnavailable,
      status,
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
