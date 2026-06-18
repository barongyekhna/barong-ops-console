"use client";

import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  abortActiveApiRequests,
  ApiError,
  AUTH_UNAUTHORIZED_EVENT,
  isApiAbortError,
} from "@/lib/api";
import {
  loginRequest,
  logoutRequest,
  sessionCheckRequest,
  type AuthenticatedUser,
} from "@/lib/auth";

type AuthStatus = "checking" | "authenticated" | "unauthenticated" | "error";

type AuthContextValue = {
  status: AuthStatus;
  user: AuthenticatedUser | null;
  login: (
    username: string,
    password: string,
    options?: { signal?: AbortSignal; timeoutMs?: number },
  ) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const previousPathnameRef = useRef(pathname);
  const sessionCheckGenerationRef = useRef(0);

  const clearSession = useCallback(() => {
    sessionCheckGenerationRef.current += 1;
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  const refresh = useCallback(async () => {
    const generation = sessionCheckGenerationRef.current + 1;
    sessionCheckGenerationRef.current = generation;
    setStatus("checking");
    try {
      const currentUser = await sessionCheckRequest();
      if (sessionCheckGenerationRef.current !== generation) {
        return;
      }

      setUser(currentUser);
      setStatus("authenticated");
    } catch (error) {
      if (sessionCheckGenerationRef.current !== generation) {
        return;
      }

      if (
        (error instanceof ApiError && error.status === 401) ||
        isApiAbortError(error)
      ) {
        clearSession();
        return;
      }

      setUser(null);
      setStatus("error");
    }
  }, [clearSession]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useLayoutEffect(() => {
    if (previousPathnameRef.current === pathname) {
      return;
    }

    previousPathnameRef.current = pathname;
    abortActiveApiRequests();
  }, [pathname]);

  useEffect(() => {
    const handleUnauthorized = () => clearSession();

    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);

    return () => {
      window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
    };
  }, [clearSession]);

  const login = useCallback(
    async (
      username: string,
      password: string,
      options: { signal?: AbortSignal; timeoutMs?: number } = {},
    ) => {
      sessionCheckGenerationRef.current += 1;

      try {
        const result = await loginRequest(username, password, options);
        sessionCheckGenerationRef.current += 1;
        setUser(result.user);
        setStatus("authenticated");
      } catch (error) {
        setUser(null);
        setStatus("unauthenticated");
        throw error;
      }
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const value = useMemo(
    () => ({ status, user, login, logout, refresh }),
    [status, user, login, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider.");
  }

  return context;
}
