"use client";

import {
  clearFrontendRequestCache,
  requestWithFrontendCache,
} from "@/lib/request-cache";

export const AUTH_UNAUTHORIZED_EVENT = "barong-auth-unauthorized";

const API_PROXY_BASE = "/api/backend";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type ApiRequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
};

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");

  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  return requestWithFrontendCache<T>(
    path,
    {
      body: options.body,
      method,
    },
    async () => {
      const response = await fetch(`${API_PROXY_BASE}${path}`, {
        ...options,
        body:
          options.body === undefined ? undefined : JSON.stringify(options.body),
        cache: "no-store",
        credentials: "include",
        headers,
        method,
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
    }
  );
}
