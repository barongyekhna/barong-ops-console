import { NextRequest } from "next/server";

const ALLOWED_AUTH_PATHS = new Set([
  "auth/login",
  "auth/logout",
  "auth/me",
]);
const ALLOWED_LIST_PATHS = new Set([
  "modules",
  "agents",
  "workflows",
  "jobs",
  "artifacts",
  "reviews",
  "errors",
  "memory-events",
]);
const ALLOWED_USER_ACTIONS = new Set([
  "disable",
  "enable",
  "reset-password",
]);

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function getApiBaseUrl() {
  const configuredUrl =
    process.env.BACKEND_API_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL;

  if (!configuredUrl) {
    throw new Error("Backend API URL is not configured.");
  }

  const parsedUrl = new URL(configuredUrl);
  if (!["http:", "https:"].includes(parsedUrl.protocol)) {
    throw new Error("Backend API URL must use HTTP or HTTPS.");
  }

  if (parsedUrl.username || parsedUrl.password) {
    throw new Error("Backend API URL must not contain credentials.");
  }

  return parsedUrl;
}

function isIntegerPathSegment(segment: string) {
  return /^[1-9]\d*$/.test(segment);
}

function isAllowedUsersPath(method: string, path: string[]) {
  if (path[0] !== "users") {
    return false;
  }

  if (path.length === 1) {
    return method === "GET" || method === "POST";
  }

  if (path.length === 2 && path[1] === "roles") {
    return method === "GET";
  }

  if (path.length === 2 && isIntegerPathSegment(path[1])) {
    return method === "GET" || method === "PATCH";
  }

  if (
    path.length === 3 &&
    isIntegerPathSegment(path[1]) &&
    ALLOWED_USER_ACTIONS.has(path[2])
  ) {
    return method === "POST";
  }

  return false;
}

async function proxyRequest(
  request: NextRequest,
  context: RouteContext,
) {
  const { path } = await context.params;
  const requestedPath = path.join("/");

  const isHealthPath = request.method === "GET" && requestedPath === "health";
  const isAuthPath = ALLOWED_AUTH_PATHS.has(requestedPath);
  const isListPath =
    request.method === "GET" && ALLOWED_LIST_PATHS.has(requestedPath);
  const isFoundationDemoPath =
    (request.method === "POST" && requestedPath === "foundation-demo/run") ||
    (request.method === "GET" && requestedPath === "foundation-demo/latest");
  const isN8nTestPath =
    (request.method === "POST" && requestedPath === "n8n-test/run") ||
    (request.method === "GET" && requestedPath === "n8n-test/latest");
  const isUsersPath = isAllowedUsersPath(request.method, path);

  if (
    !isHealthPath &&
    !isAuthPath &&
    !isListPath &&
    !isFoundationDemoPath &&
    !isN8nTestPath &&
    !isUsersPath
  ) {
    return Response.json({ detail: "Not found." }, { status: 404 });
  }

  try {
    const targetUrl = new URL(`/${requestedPath}`, getApiBaseUrl());
    targetUrl.search = request.nextUrl.search;
    const headers = new Headers({
      Accept: "application/json",
    });
    const authorization = request.headers.get("authorization");
    const contentType = request.headers.get("content-type");

    if (authorization) {
      headers.set("Authorization", authorization);
    }
    if (contentType) {
      headers.set("Content-Type", contentType);
    }

    const requestBody =
      request.method === "GET" ? undefined : await request.text();
    const backendResponse = await fetch(targetUrl, {
      body: requestBody || undefined,
      cache: "no-store",
      headers,
      method: request.method,
    });
    const responseHeaders = new Headers();
    const backendContentType = backendResponse.headers.get("content-type");
    const authenticate = backendResponse.headers.get("www-authenticate");

    if (backendContentType) {
      responseHeaders.set("Content-Type", backendContentType);
    }
    if (authenticate) {
      responseHeaders.set("WWW-Authenticate", authenticate);
    }

    return new Response(backendResponse.body, {
      headers: responseHeaders,
      status: backendResponse.status,
    });
  } catch {
    return Response.json(
      { detail: "Backend API service is unavailable." },
      { status: 503 },
    );
  }
}

export function GET(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}

export function POST(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}

export function PATCH(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}
