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

import { ApiError, AUTH_UNAUTHORIZED_EVENT } from "@/lib/api";
import {
  ACCESS_TOKEN_STORAGE_KEY,
  currentUserRequest,
  loginRequest,
  logoutRequest,
  readAccessToken,
  type AuthenticatedUser,
} from "@/lib/auth";

type AuthStatus = "checking" | "authenticated" | "unauthenticated" | "error";

type AuthContextValue = {
  status: AuthStatus;
  user: AuthenticatedUser | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function clearStoredSession() {
  window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [user, setUser] = useState<AuthenticatedUser | null>(null);

  const clearSession = useCallback(() => {
    clearStoredSession();
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  const refresh = useCallback(async () => {
    const accessToken = readAccessToken();
    if (!accessToken) {
      setUser(null);
      setStatus("unauthenticated");
      return;
    }

    setStatus("checking");
    try {
      const currentUser = await currentUserRequest(accessToken);
      setUser(currentUser);
      setStatus("authenticated");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
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

  useEffect(() => {
    const handleUnauthorized = () => clearSession();
    const handleStorage = (event: StorageEvent) => {
      if (event.key === ACCESS_TOKEN_STORAGE_KEY) {
        void refresh();
      }
    };

    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
    window.addEventListener("storage", handleStorage);

    return () => {
      window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
      window.removeEventListener("storage", handleStorage);
    };
  }, [clearSession, refresh]);

  const login = useCallback(
    async (username: string, password: string) => {
      const result = await loginRequest(username, password);
      window.localStorage.setItem(
        ACCESS_TOKEN_STORAGE_KEY,
        result.access_token,
      );

      let sessionUser = result.user;
      try {
        sessionUser = await currentUserRequest(result.access_token);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          clearSession();
          throw error;
        }
      }

      setUser(sessionUser);
      setStatus("authenticated");
    },
    [clearSession],
  );

  const logout = useCallback(async () => {
    const accessToken = readAccessToken();

    try {
      if (accessToken) {
        await logoutRequest(accessToken);
      }
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
