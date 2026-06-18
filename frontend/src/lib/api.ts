"use client";

import {
  clearFrontendRequestCache,
  requestWithFrontendCache,
} from "@/lib/request-cache";

export const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

const API_PROXY_BASE = "/api/backend";
export const DEFAULT_API_TIMEOUT_MS = 5_000;
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
    super(`The request timed out after ${timeoutMs}ms.`);
    this.name = "ApiTimeoutError";
  }
}

type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  retryLimit?: number;
  timeoutMs?: number;
};

function normalizeTimeoutMs(timeoutMs: number | undefined) {
  if (typeof timeoutMs !== "number" || !Number.isFinite(timeoutMs)) {
    return DEFAULT_API_TIMEOUT_MS;
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

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const {
    body,
    retryLimit: retryLimitOption,
    timeoutMs: timeoutMsOption,
    ...fetchOptions
  } = options;
  const method = (fetchOptions.method ?? "GET").toUpperCase();
  const headers = new Headers(fetchOptions.headers);
  const timeoutMs = normalizeTimeoutMs(timeoutMsOption);
  const retryLimit = normalizeRetryLimit(retryLimitOption);
  const requestStartedAt = Date.now();
  const routeAbortGeneration = activeRouteAbortGeneration;
  const externalSignal = fetchOptions.signal ?? null;
  headers.set("Accept", "application/json");

  if (body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  return requestWithFrontendCache<T>(
    path,
    {
      body,
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
          const response = await fetch(`${API_PROXY_BASE}${path}`, {
            ...fetchOptions,
            body: body === undefined ? undefined : JSON.stringify(body),
            cache: "no-store",
            credentials: "include",
            headers,
            method,
            signal: controller.signal,
          });

          if (response.status === 401 && typeof window !== "undefined") {
            clearFrontendRequestCache();
            window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
          }

          if (!response.ok) {
            let message = "The request could not be completed.";
            try {
              const payload = (await response.json()) as { detail?: unknown };
              if (typeof payload.detail === "string") {
                message = payload.detail;
              }
            } catch {
              // Keep the stable fallback when the backend does not return JSON.
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
