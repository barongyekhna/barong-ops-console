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
  changePasswordRequest,
  loginRequest,
  logoutRequest,
  requiresPasswordChange,
  sessionCheckRequest,
  type AuthenticatedUser,
} from "@/lib/auth";
import { isOwnerRole } from "@/lib/roles";

type AuthStatus = "checking" | "authenticated" | "unauthenticated";
type AuthLoginResult = {
  authComplete: true;
  message: string | null;
  requirePasswordChange: boolean;
  sessionToken: string;
};

type AuthContextValue = {
  status: AuthStatus;
  user: AuthenticatedUser | null;
  isOwner: boolean;
  login: (
    username: string,
    password: string,
    options?: { signal?: AbortSignal; timeoutMs?: number },
  ) => Promise<AuthLoginResult>;
  changePassword: (
    currentPassword: string,
    newPassword: string,
    options?: { signal?: AbortSignal; timeoutMs?: number },
  ) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  resetAuthState: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);
const LOGIN_PATHNAME = "/login";
const BACKGROUND_SESSION_CHECK_TIMEOUT_MS = 1_500;
const AUTH_SESSION_STORAGE_KEY = "barong-auth-session";

type StoredAuthSession = {
  authComplete: true;
  sessionToken: string;
  user: AuthenticatedUser | null;
};

function readStoredAuthSession(): StoredAuthSession | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const rawValue = window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY);
    if (!rawValue) {
      return null;
    }
    const parsed = JSON.parse(rawValue) as Partial<StoredAuthSession>;
    if (
      parsed.authComplete !== true ||
      typeof parsed.sessionToken !== "string" ||
      !parsed.sessionToken
    ) {
      return null;
    }

    const user =
      parsed.user &&
      typeof parsed.user.id === "number" &&
      typeof parsed.user.role === "string"
        ? parsed.user
        : null;
    return {
      authComplete: true,
      sessionToken: parsed.sessionToken,
      user,
    };
  } catch {
    return null;
  }
}

function writeStoredAuthSession(session: StoredAuthSession) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    // **绝不把会话令牌写进 localStorage。**
    // 2026-08-31 体检：这里原本存的是完整的 { sessionToken } 明文，而同一次登录
    // 的 cookie 是 HttpOnly + Secure、30 天有效。任何一次 XSS 只要一行
    // localStorage.getItem 就能把令牌拿走，HttpOnly 的保护被完全抵消 ——
    // 而控制台里渲染外部文本的地方不少（通知正文、C19 消息、K 的 AI 产出）。
    //
    // 鉴权本来就不依赖它：前端代理会把浏览器的 Cookie 原样转发给后端
    // （api/backend/[...path]/route.ts 里 headers.set("Cookie", cookie)），
    // 读取方拿不到令牌时只是不设 x-session-token 头，cookie 照常完成鉴权。
    // 这里只留「登录过」和用户信息这类非机密字段，供刷新时快速回显。
    const { sessionToken: _omitted, ...safeFields } = session;
    void _omitted;
    window.localStorage.setItem(
      AUTH_SESSION_STORAGE_KEY,
      JSON.stringify(safeFields),
    );
  } catch {
    // Browser storage can be unavailable; the HttpOnly cookie still carries auth.
  }
}

function clearStoredAuthSession() {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
  } catch {
    // Ignore storage failures; in-memory state is cleared by the caller.
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  // Deterministic initial state: identical on the server render and the client's
  // first render so hydration matches. Reading localStorage in these
  // initializers caused a React #418 hydration mismatch on EVERY page (server
  // saw no session → "checking"; client saw the stored session →
  // "authenticated"). The persisted session is restored after mount, in an
  // effect (see below), which is the only safe place to touch localStorage.
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const previousPathnameRef = useRef(pathname);
  const authSnapshotRef = useRef<{
    status: AuthStatus;
    user: AuthenticatedUser | null;
  }>({ status, user });
  const sessionCheckAbortControllerRef = useRef<AbortController | null>(null);
  const sessionCheckGenerationRef = useRef(0);
  const loginInFlightRef = useRef<Promise<AuthLoginResult> | null>(null);
  const sessionTokenRef = useRef<string | null>(null);
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
    sessionTokenRef.current = null;
    clearStoredAuthSession();
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  const resetAuthState = useCallback(() => {
    sessionCheckGenerationRef.current += 1;
    abortSessionCheck("The session check was aborted because auth state reset.");
    sessionTokenRef.current = null;
    clearStoredAuthSession();
    setUser(null);
    setStatus("unauthenticated");
  }, [abortSessionCheck]);

  const refresh = useCallback(async () => {
    if (pathname === LOGIN_PATHNAME) {
      if (sessionTokenRef.current) {
        setStatus("authenticated");
        return;
      }
      setUser(null);
      setStatus("unauthenticated");
      return;
    }

    const supplementalOnly = sessionTokenRef.current !== null;

    const generation = sessionCheckGenerationRef.current + 1;
    sessionCheckGenerationRef.current = generation;
    abortSessionCheck("The session check was replaced by a newer request.");
    const controller = new AbortController();
    sessionCheckAbortControllerRef.current = controller;
    if (!supplementalOnly) {
      setStatus("checking");
    }

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
      if (sessionTokenRef.current) {
        writeStoredAuthSession({
          authComplete: true,
          sessionToken: sessionTokenRef.current,
          user: currentUser,
        });
      }
    } catch (error) {
      if (
        sessionCheckGenerationRef.current !== generation ||
        controller.signal.aborted ||
        isApiAbortError(error)
      ) {
        return;
      }

      if (supplementalOnly) {
        setStatus("authenticated");
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

  // Restore any persisted session AFTER mount (never during render — see the
  // deterministic initial state above). Runs before the refresh effect below,
  // so sessionTokenRef is populated first and refresh takes the fast
  // "supplemental" validation path instead of a full "checking" reload.
  useEffect(() => {
    const stored = readStoredAuthSession();
    if (stored) {
      sessionTokenRef.current = stored.sessionToken;
      if (stored.user) {
        setUser(stored.user);
      }
      setStatus("authenticated");
    }
  }, []);

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
      if (sessionTokenRef.current) {
        setStatus("authenticated");
        return;
      }
      setUser(null);
      setStatus("unauthenticated");
      return;
    }

    if (sessionTokenRef.current) {
      setStatus("authenticated");
      return;
    }

    if (authSnapshotRef.current.status !== "authenticated") {
      setUser(null);
      setStatus("checking");
    }
  }, [abortSessionCheck, pathname]);

  useEffect(() => {
    const handleUnauthorized = () => {
      resetAuthState();
    };

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
      if (loginInFlightRef.current) {
        return loginInFlightRef.current;
      }

      sessionCheckGenerationRef.current += 1;
      abortSessionCheck("The session check was aborted because login started.");

      const loginPromise = (async () => {
        const result = await loginRequest(username, password, options);
        sessionCheckGenerationRef.current += 1;
        sessionTokenRef.current = result.session_token;
        writeStoredAuthSession({
          authComplete: true,
          sessionToken: result.session_token,
          user: result.user,
        });
        setUser(result.user);
        setStatus("authenticated");
        return {
          authComplete: result.auth_complete,
          message: result.message,
          requirePasswordChange: requiresPasswordChange(
            result.user,
            result.require_password_change,
          ),
          sessionToken: result.session_token,
        };
      })();
      loginInFlightRef.current = loginPromise;

      try {
        return await loginPromise;
      } catch (error) {
        sessionTokenRef.current = null;
        clearStoredAuthSession();
        setUser(null);
        setStatus("unauthenticated");
        throw error;
      } finally {
        if (loginInFlightRef.current === loginPromise) {
          loginInFlightRef.current = null;
        }
      }
    },
    [abortSessionCheck],
  );

  const changePassword = useCallback(
    async (
      currentPassword: string,
      newPassword: string,
      options: { signal?: AbortSignal; timeoutMs?: number } = {},
    ) => {
      const result = await changePasswordRequest(
        currentPassword,
        newPassword,
        options,
      );
      sessionCheckGenerationRef.current += 1;
      if (sessionTokenRef.current) {
        writeStoredAuthSession({
          authComplete: true,
          sessionToken: sessionTokenRef.current,
          user: result.user,
        });
      }
      setUser(result.user);
      setStatus("authenticated");
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

  const isOwner = isOwnerRole(user?.role);
  const value = useMemo(
    () => ({
      status,
      user,
      isOwner,
      login,
      changePassword,
      logout,
      refresh,
      resetAuthState,
    }),
    [
      status,
      user,
      isOwner,
      login,
      changePassword,
      logout,
      refresh,
      resetAuthState,
    ],
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
