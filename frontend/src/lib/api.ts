"use client";

import {
  clearFrontendRequestCache,
  requestWithFrontendCache,
} from "@/lib/request-cache";
import { translateC19BackendError, translateKBackendError } from "@/lib/i18n";

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
  // 显式字段 + 构造函数内赋值,**不用 TS 的「参数属性」简写**。
  // 参数属性需要编译器生成赋值代码,node 的 strip-only 类型剥离做不到,
  // 整个模块就 import 不进 `node --test` —— 这正是 2026-09-02 之前
  // 关于 apiRequest 的断言全是「读源码匹配正则」的原因。
  readonly status: number;
  readonly detail: unknown;

  constructor(
    message: string,
    status: number,
    /**
     * 后端 `detail` 的原始值。
     *
     * `message` 是给人看的一句话 —— 会被翻译器改写、会被中文兜底整句换掉。
     * 但有些接口的 `detail` 是**结构化的**,调用方要按字段读:K 的发布门禁返回
     * `{blockers: [...]}`、M 的出库返回缺料清单。这些信息以前在 apiRequest
     * 内部解析出来后就被丢掉了,调用方只剩一句话可看,清单静默消失。
     */
    detail: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export class ApiRequestAbortedError extends Error {
  constructor(message = "The request was aborted.") {
    super(message);
    this.name = "ApiRequestAbortedError";
  }
}

export class ApiTimeoutError extends ApiRequestAbortedError {
  readonly timeoutMs: number;

  constructor(timeoutMs: number) {
    super("服务暂时不可用，请稍后再试。");
    this.name = "ApiTimeoutError";
    this.timeoutMs = timeoutMs;
  }
}

type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  bypassCache?: boolean;
  retryLimit?: number;
  timeoutMs?: number;
  /**
   * 模块自己的兜底文案，用来顶替按状态码给的通用兜底。
   *
   * 为什么需要：通用兜底（「服务暂时不可用，请稍后再试。」）不说是**哪个**
   * 模块出的事。收口时一度让所有模块都退化成这句，等于把「界面失败时只给
   * 含糊提示」这个老毛病又请回来 —— 用户报「产品知识库请求未完成」我能定位，
   * 报「服务暂时不可用」就只能猜。
   */
  fallbackMessage?: string;
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
  const trimmed = message.trim();
  const normalized = trimmed.toLowerCase();
  if (
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
  ) {
    return true;
  }
  // 通用启发式:整个 UI 是中文,任何不含中文的后端英文/工程串(异常文本、
  // 字段名、堆栈等)都不该原样呈现给用户 → 判为技术串,由调用方按状态兜底。
  if (trimmed && !/[一-鿿]/.test(trimmed)) {
    return true;
  }
  return false;
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
    fallbackMessage,
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

  // multipart 的 boundary 是 fetch 自己按 FormData 生成并写进 Content-Type 的。
  // 我们一旦手动设成 application/json,boundary 就没了,后端解析必然失败。
  const isFormDataBody =
    typeof FormData !== "undefined" && body instanceof FormData;

  if (body !== undefined && !isFormDataBody) {
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
            body:
              body === undefined
                ? undefined
                : isFormDataBody
                  ? (body as FormData)
                  : JSON.stringify(body),
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
            let message =
              fallbackMessage ?? fallbackErrorMessageForStatus(response.status);
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
            const statusFallback =
              fallbackMessage ?? fallbackErrorMessageForStatus(response.status);
            if (backendPath.startsWith("/k/")) {
              message = translateKBackendError({
                detail: errorDetail,
                fallback: statusFallback,
                message,
                path: backendPath,
                status: response.status,
              });
            } else if (backendPath.startsWith("/c19")) {
              message = translateC19BackendError({
                detail: errorDetail,
                fallback: statusFallback,
                message,
                status: response.status,
              });
            }
            // 通用兜底:任何仍是英文/工程串(未被翻译器认出的后端文案)一律
            // 换成中文状态兜底,保证前端永不出现原始英文报错。
            if (isTechnicalErrorMessage(message)) {
              message = statusFallback;
            }
            throw new ApiError(message, response.status, errorDetail);
          }

          // 204 No Content / 205 Reset Content 按规范**不带响应体**,
          // 直接 response.json() 会抛 SyntaxError。DELETE 类接口大量返回 204,
          // 不处理这条,收口第一个模块就会红。
          if (response.status === 204 || response.status === 205) {
            return undefined as T;
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
