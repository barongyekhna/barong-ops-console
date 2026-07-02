"use client";

import {
  clearFrontendRequestCache,
  requestWithFrontendCache,
} from "@/lib/request-cache";
import { translateKBackendError } from "@/lib/i18n";

export const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

const API_PROXY_BASE = "/api/backend";
const AUTH_SESSION_STORAGE_KEY = "barong-auth-session";
const SESSION_TOKEN_HEADER = "X-Session-Token";
const FRONTEND_FORCE_REFRESH_HEADER = "X-Frontend-Force-Refresh";
export const DEFAULT_API_TIMEOUT_MS = 15_000;
const CAPABILITY_BOOTSTRAP_TIMEOUT_MS = 30_000;
const MODULE_CONTROL_TIMEOUT_MS = 60_000;
const DEFAULT_API_RETRY_LIMIT = 1;
const RETRYABLE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

let activeRouteAbortGeneration = 0;
const activeApiControllers = new Set<AbortController>();

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class ApiRequestAbortedError extends Error {
  constructor(message = "The request was aborted.") {
    super(message);
    this.name = "ApiRequestAbortedError";
  }
}

export class ApiTimeoutError extends ApiRequestAbortedError {
  constructor(readonly timeoutMs: number) {
    super("服务暂时不可用，请稍后再试。");
    this.name = "ApiTimeoutError";
  }
}

type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  bypassCache?: boolean;
  retryLimit?: number;
  timeoutMs?: number;
};

function toBackendRequestPath(path: string) {
  const parsedPath = new URL(path, "https://frontend.local");
  const pathname = parsedPath.pathname;
  const search = parsedPath.search;

  if (pathname === API_PROXY_BASE) {
    return `/${search}`;
  }
  if (pathname.startsWith(`${API_PROXY_BASE}/`)) {
    return `${pathname.slice(API_PROXY_BASE.length)}${search}`;
  }

  return `${pathname}${search}`;
}

function toFrontendProxyPath(path: string) {
  const backendPath = toBackendRequestPath(path);
  if (backendPath === "/") {
    return API_PROXY_BASE;
  }

  return `${API_PROXY_BASE}${backendPath}`;
}

function defaultTimeoutMsForPath(path: string, method: string) {
  if (method !== "GET") {
    return DEFAULT_API_TIMEOUT_MS;
  }

  const normalizedPath = new URL(path, "https://frontend.local").pathname;
  if (normalizedPath === "/capability/bootstrap") {
    return CAPABILITY_BOOTSTRAP_TIMEOUT_MS;
  }
  if (normalizedPath === "/module-control/center") {
    return MODULE_CONTROL_TIMEOUT_MS;
  }

  return DEFAULT_API_TIMEOUT_MS;
}

function normalizeTimeoutMs(
  timeoutMs: number | undefined,
  path: string,
  method: string,
) {
  if (typeof timeoutMs !== "number" || !Number.isFinite(timeoutMs)) {
    return defaultTimeoutMsForPath(path, method);
  }

  return Math.max(1, Math.floor(timeoutMs));
}

function normalizeRetryLimit(retryLimit: number | undefined) {
  if (typeof retryLimit !== "number" || !Number.isFinite(retryLimit)) {
    return DEFAULT_API_RETRY_LIMIT;
  }

  return Math.max(0, Math.floor(retryLimit));
}

function isAbortLikeError(error: unknown) {
  return (
    error instanceof ApiRequestAbortedError ||
    (typeof error === "object" &&
      error !== null &&
      "name" in error &&
      (error as { name?: unknown }).name === "AbortError")
  );
}

export function isApiAbortError(error: unknown) {
  return isAbortLikeError(error);
}

function routeChangedError() {
  return new ApiRequestAbortedError(
    "The request was aborted because the route changed.",
  );
}

export function abortActiveApiRequests(
  reason: ApiRequestAbortedError = routeChangedError(),
) {
  activeRouteAbortGeneration += 1;

  for (const controller of activeApiControllers) {
    if (!controller.signal.aborted) {
      controller.abort(reason);
    }
  }
}

function createAttemptController(
  timeoutMs: number,
  externalSignal: AbortSignal | null,
) {
  const controller = new AbortController();
  let timeoutId: ReturnType<typeof setTimeout> | null = null;

  const abortFromExternalSignal = () => {
    if (!controller.signal.aborted) {
      controller.abort(
        externalSignal?.reason instanceof Error
          ? externalSignal.reason
          : new ApiRequestAbortedError(),
      );
    }
  };

  timeoutId = setTimeout(() => {
    if (!controller.signal.aborted) {
      controller.abort(new ApiTimeoutError(timeoutMs));
    }
  }, timeoutMs);

  if (externalSignal) {
    if (externalSignal.aborted) {
      abortFromExternalSignal();
    } else {
      externalSignal.addEventListener("abort", abortFromExternalSignal, {
        once: true,
      });
    }
  }

  activeApiControllers.add(controller);

  return {
    controller,
    dispose: () => {
      if (timeoutId !== null) {
        clearTimeout(timeoutId);
      }
      if (externalSignal) {
        externalSignal.removeEventListener("abort", abortFromExternalSignal);
      }
      activeApiControllers.delete(controller);
    },
  };
}

function toAbortError(signal: AbortSignal, timeoutMs: number) {
  if (signal.reason instanceof Error) {
    return signal.reason;
  }

  return new ApiTimeoutError(timeoutMs);
}

function isRetryableError(error: unknown, method: string) {
  if (!RETRYABLE_METHODS.has(method)) {
    return false;
  }

  if (isAbortLikeError(error)) {
    return false;
  }

  if (error instanceof ApiError) {
    return error.status >= 500 || error.status === 429;
  }

  return error instanceof TypeError;
}

function shouldDispatchUnauthorized(path: string) {
  const normalizedPath = new URL(path, "https://frontend.local").pathname;
  return normalizedPath !== "/auth/login" && normalizedPath !== "/auth/me";
}

function fallbackErrorMessageForStatus(status: number) {
  if (status === 401) {
    return "请重新登录后继续。";
  }
  if (status === 403) {
    return "当前账号无权执行此操作。";
  }
  if (status === 404) {
    return "没有找到对应内容。";
  }
  if (status === 409) {
    return "当前操作与已有数据冲突。";
  }
  if (status === 422) {
    return "请检查填写内容后再提交。";
  }
  if (status === 429) {
    return "操作太频繁，请稍后再试。";
  }
  if (status >= 500) {
    return "服务暂时不可用，请稍后再试。";
  }
  return "请求未完成，请稍后再试。";
}

function isTechnicalErrorMessage(message: string) {
  const normalized = message.trim().toLowerCase();
  return (
    normalized === "not authenticated." ||
    normalized === "not authenticated" ||
    normalized === "internal server error." ||
    normalized === "internal server error" ||
    normalized === "forbidden." ||
    normalized === "forbidden" ||
    normalized === "invalid request." ||
    normalized === "invalid request" ||
    normalized === "request failed." ||
    normalized === "request failed" ||
    normalized === "加载失败，请稍后重试。" ||
    normalized === "服务暂时不可用，请稍后重试。"
  );
}

function storedSessionToken() {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const rawValue = window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY);
    if (!rawValue) {
      return null;
    }
    const parsed = JSON.parse(rawValue) as {
      authComplete?: unknown;
      sessionToken?: unknown;
    };
    if (
      parsed.authComplete === true &&
      typeof parsed.sessionToken === "string" &&
      parsed.sessionToken
    ) {
      return parsed.sessionToken;
    }
  } catch {
    return null;
  }

  return null;
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const {
    body,
    bypassCache = false,
    retryLimit: retryLimitOption,
    timeoutMs: timeoutMsOption,
    ...fetchOptions
  } = options;
  const method = (fetchOptions.method ?? "GET").toUpperCase();
  const headers = new Headers(fetchOptions.headers);
  const backendPath = toBackendRequestPath(path);
  const frontendProxyPath = toFrontendProxyPath(path);
  const timeoutMs = normalizeTimeoutMs(timeoutMsOption, backendPath, method);
  const retryLimit = normalizeRetryLimit(retryLimitOption);
  const requestStartedAt = Date.now();
  const routeAbortGeneration = activeRouteAbortGeneration;
  const externalSignal = fetchOptions.signal ?? null;
  headers.set("Accept", "application/json");

  if (body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const sessionToken = storedSessionToken();
  if (sessionToken && !headers.has(SESSION_TOKEN_HEADER)) {
    headers.set(SESSION_TOKEN_HEADER, sessionToken);
  }
  if (bypassCache) {
    headers.set(FRONTEND_FORCE_REFRESH_HEADER, "1");
  }

  return requestWithFrontendCache<T>(
    backendPath,
    {
      body,
      bypassCache,
      method,
    },
    async () => {
      let attempts = 0;

      while (true) {
        if (routeAbortGeneration !== activeRouteAbortGeneration) {
          throw routeChangedError();
        }

        const elapsedMs = Date.now() - requestStartedAt;
        const remainingTimeoutMs = Math.max(1, timeoutMs - elapsedMs);

        if (elapsedMs >= timeoutMs) {
          throw new ApiTimeoutError(timeoutMs);
        }

        const { controller, dispose } = createAttemptController(
          remainingTimeoutMs,
          externalSignal,
        );

        try {
          const response = await fetch(frontendProxyPath, {
            ...fetchOptions,
            body: body === undefined ? undefined : JSON.stringify(body),
            cache: "no-store",
            credentials: "include",
            headers,
            method,
            signal: controller.signal,
          });

          if (
            response.status === 401 &&
            typeof window !== "undefined" &&
            shouldDispatchUnauthorized(backendPath)
          ) {
            clearFrontendRequestCache();
            window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
          }

          if (!response.ok) {
            let message = fallbackErrorMessageForStatus(response.status);
            let errorDetail: unknown = null;
            try {
              const payload = (await response.json()) as { detail?: unknown };
              errorDetail = payload.detail ?? null;
              if (typeof payload.detail === "string") {
                message = payload.detail;
              } else if (
                typeof payload.detail === "object" &&
                payload.detail !== null &&
                "message" in payload.detail &&
                typeof (payload.detail as { message?: unknown }).message ===
                  "string"
              ) {
                message = (payload.detail as { message: string }).message;
              }
            } catch {
              // Keep the stable fallback when the backend does not return JSON.
            }
            if (isTechnicalErrorMessage(message)) {
              message = fallbackErrorMessageForStatus(response.status);
            }
            if (backendPath.startsWith("/k/")) {
              message = translateKBackendError({
                detail: errorDetail,
                fallback: fallbackErrorMessageForStatus(response.status),
                message,
                path: backendPath,
                status: response.status,
              });
            }
            throw new ApiError(message, response.status);
          }

          return (await response.json()) as T;
        } catch (error) {
          const normalizedError =
            controller.signal.aborted && isAbortLikeError(error)
              ? toAbortError(controller.signal, timeoutMs)
              : error;

          if (
            attempts >= retryLimit ||
            !isRetryableError(normalizedError, method)
          ) {
            throw normalizedError;
          }

          attempts += 1;
        } finally {
          dispose();
        }
      }
    }
  );
}
