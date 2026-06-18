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
  ApiRequestAbortedError,
  AUTH_UNAUTHORIZED_EVENT,
  isApiAbortError,
} from "@/lib/api";
import {
  loginRequest,
  logoutRequest,
  sessionCheckRequest,
  type AuthenticatedUser,
} from "@/lib/auth";

type AuthStatus = "checking" | "authenticated" | "unauthenticated";

type AuthContextValue = {
  status: AuthStatus;
  user: AuthenticatedUser | null;
  isOwner: boolean;
  login: (
    username: string,
    password: string,
    options?: { signal?: AbortSignal; timeoutMs?: number },
  ) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  resetAuthState: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);
const LOGIN_PATHNAME = "/login";
const BACKGROUND_SESSION_CHECK_TIMEOUT_MS = 1_500;

export function AuthProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [status, setStatus] = useState<AuthStatus>(() =>
    pathname === LOGIN_PATHNAME ? "unauthenticated" : "checking",
  );
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const previousPathnameRef = useRef(pathname);
  const authSnapshotRef = useRef<{
    status: AuthStatus;
    user: AuthenticatedUser | null;
  }>({ status, user });
  const sessionCheckAbortControllerRef = useRef<AbortController | null>(null);
  const sessionCheckGenerationRef = useRef(0);
  authSnapshotRef.current = { status, user };

  const abortSessionCheck = useCallback((message: string) => {
    const controller = sessionCheckAbortControllerRef.current;
    sessionCheckAbortControllerRef.current = null;

    if (controller && !controller.signal.aborted) {
      controller.abort(new ApiRequestAbortedError(message));
    }
  }, []);

  const clearSession = useCallback(() => {
    sessionCheckGenerationRef.current += 1;
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  const resetAuthState = useCallback(() => {
    sessionCheckGenerationRef.current += 1;
    abortSessionCheck("The session check was aborted because auth state reset.");
    setUser(null);
    setStatus("unauthenticated");
  }, [abortSessionCheck]);

  const refresh = useCallback(async () => {
    if (pathname === LOGIN_PATHNAME) {
      resetAuthState();
      return;
    }

    if (
      authSnapshotRef.current.status === "authenticated" &&
      authSnapshotRef.current.user
    ) {
      return;
    }

    const generation = sessionCheckGenerationRef.current + 1;
    sessionCheckGenerationRef.current = generation;
    abortSessionCheck("The session check was replaced by a newer request.");
    const controller = new AbortController();
    sessionCheckAbortControllerRef.current = controller;
    setStatus("checking");

    try {
      const currentUser = await sessionCheckRequest({
        signal: controller.signal,
        timeoutMs: BACKGROUND_SESSION_CHECK_TIMEOUT_MS,
      });
      if (
        sessionCheckGenerationRef.current !== generation ||
        controller.signal.aborted
      ) {
        return;
      }

      setUser(currentUser);
      setStatus("authenticated");
    } catch (error) {
      if (
        sessionCheckGenerationRef.current !== generation ||
        controller.signal.aborted ||
        isApiAbortError(error)
      ) {
        return;
      }

      if (error instanceof ApiError && error.status === 401) {
        clearSession();
        return;
      }

      clearSession();
    } finally {
      if (sessionCheckAbortControllerRef.current === controller) {
        sessionCheckAbortControllerRef.current = null;
      }
    }
  }, [abortSessionCheck, clearSession, pathname, resetAuthState]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useLayoutEffect(() => {
    if (previousPathnameRef.current === pathname) {
      return;
    }

    previousPathnameRef.current = pathname;
    abortActiveApiRequests();
    abortSessionCheck(
      "The session check was aborted because the route changed.",
    );
    sessionCheckGenerationRef.current += 1;

    if (pathname === LOGIN_PATHNAME) {
      setUser(null);
      setStatus("unauthenticated");
      return;
    }

    if (authSnapshotRef.current.status !== "authenticated") {
      setUser(null);
      setStatus("checking");
    }
  }, [abortSessionCheck, pathname]);

  useEffect(() => {
    const handleUnauthorized = () => resetAuthState();

    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);

    return () => {
      window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized);
    };
  }, [resetAuthState]);

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
      resetAuthState();
    }
  }, [resetAuthState]);

  const isOwner = user?.role === "owner";
  const value = useMemo(
    () => ({ status, user, isOwner, login, logout, refresh, resetAuthState }),
    [status, user, isOwner, login, logout, refresh, resetAuthState],
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
