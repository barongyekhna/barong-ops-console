"use client";

const DEFAULT_CACHE_TTL_MS = 45_000;
const AUTH_ME_CACHE_TTL_MS = 30_000;
const CAPABILITY_BOOTSTRAP_CACHE_TTL_MS = 30_000;
const MAX_CONCURRENT_FRONTEND_REQUESTS = 6;

type CacheEntry<T> = {
  expiresAt: number;
  value: T;
};

type QueuedRequest = () => void;

const memoryCache = new Map<string, CacheEntry<unknown>>();
const inFlightRequests = new Map<string, Promise<unknown>>();
const requestQueue: QueuedRequest[] = [];

let activeRequestCount = 0;

function now() {
  return Date.now();
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }

  if (Array.isArray(value)) {
    return `[${value.map((item) => stableJson(item)).join(",")}]`;
  }

  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`)
    .join(",")}}`;
}

function normalizePath(path: string) {
  const url = new URL(path, "https://frontend.local");
  const searchParams = Array.from(url.searchParams.entries()).sort(
    ([leftKey, leftValue], [rightKey, rightValue]) =>
      leftKey === rightKey
        ? leftValue.localeCompare(rightValue)
        : leftKey.localeCompare(rightKey),
  );
  const normalizedSearch =
    searchParams.length > 0
      ? `?${new URLSearchParams(searchParams).toString()}`
      : "";

  return `${url.pathname}${normalizedSearch}`;
}

function cacheTtlForPath(path: string) {
  const normalizedPath = normalizePath(path);

  if (normalizedPath === "/auth/me") {
    return AUTH_ME_CACHE_TTL_MS;
  }

  if (normalizedPath === "/capability/bootstrap") {
    return CAPABILITY_BOOTSTRAP_CACHE_TTL_MS;
  }

  if (
    normalizedPath === "/modules/registry" ||
    normalizedPath === "/modules/me" ||
    normalizedPath === "/permissions/me" ||
    normalizedPath.startsWith("/module-adapters/") ||
    normalizedPath.startsWith("/execution-providers/") ||
    normalizedPath.startsWith("/live-gate/")
  ) {
    return DEFAULT_CACHE_TTL_MS;
  }

  return 0;
}

function releaseNextRequest() {
  activeRequestCount = Math.max(0, activeRequestCount - 1);
  const next = requestQueue.shift();

  if (next) {
    next();
  }
}

function runWithConcurrencyLimit<T>(request: () => Promise<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const run = () => {
      activeRequestCount += 1;
      request()
        .then(resolve, reject)
        .finally(releaseNextRequest);
    };

    if (activeRequestCount < MAX_CONCURRENT_FRONTEND_REQUESTS) {
      run();
      return;
    }

    requestQueue.push(run);
  });
}

export function clearFrontendRequestCache() {
  memoryCache.clear();
}

export function getFrontendRequestCacheStats() {
  return {
    active: activeRequestCount,
    cached: memoryCache.size,
    inFlight: inFlightRequests.size,
    maxConcurrent: MAX_CONCURRENT_FRONTEND_REQUESTS,
    queued: requestQueue.length,
  };
}

export function getFrontendRequestCacheKey(
  path: string,
  options: {
    body?: unknown;
    method?: string;
  } = {},
) {
  const method = (options.method ?? "GET").toUpperCase();
  const bodyKey =
    method === "GET" || options.body === undefined
      ? ""
      : ` body:${stableJson(options.body)}`;

  return `${method} ${normalizePath(path)}${bodyKey}`;
}

export async function requestWithFrontendCache<T>(
  path: string,
  options: {
    body?: unknown;
    method?: string;
  },
  request: () => Promise<T>,
): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const cacheKey = getFrontendRequestCacheKey(path, {
    body: options.body,
    method,
  });
  const canUseMemoryCache = method === "GET";
  const ttl = canUseMemoryCache ? cacheTtlForPath(path) : 0;

  if (method !== "GET") {
    clearFrontendRequestCache();
  }

  if (ttl > 0) {
    const cached = memoryCache.get(cacheKey);
    if (cached && cached.expiresAt > now()) {
      return cached.value as T;
    }
    if (cached) {
      memoryCache.delete(cacheKey);
    }
  }

  const inFlight = inFlightRequests.get(cacheKey);
  if (inFlight) {
    return inFlight as Promise<T>;
  }

  const promise = runWithConcurrencyLimit(request)
    .then((value) => {
      if (ttl > 0) {
        memoryCache.set(cacheKey, {
          expiresAt: now() + ttl,
          value,
        });
      }

      return value;
    })
    .finally(() => {
      inFlightRequests.delete(cacheKey);
    });

  inFlightRequests.set(cacheKey, promise);

  return promise;
}
