import type { NextRequest } from "next/server";

const PUBLIC_API_PREFIX = "/api/public";
const APPLICATION_API_PREFIX = "/api/app";
const CONTROL_PLANE_API_PREFIX = "/api/control-plane";

const ALLOWED_PUBLIC_GET_PATHS = new Set([
  "health",
  "auth/me",
]);
const ALLOWED_PUBLIC_POST_PATHS = new Set([
  "auth/login",
  "auth/logout",
]);
const ALLOWED_APP_LIST_PATHS = new Set([
  "jobs",
  "artifacts",
  "reviews",
  "errors",
  "memory-events",
  "operation-logs",
  "approval/list",
]);
const ALLOWED_CONTROL_PLANE_LIST_PATHS = new Set([
  "modules",
  "agents",
  "workflows",
]);
const ALLOWED_USER_ACTIONS = new Set([
  "disable",
  "enable",
  "reset-password",
]);
const ALLOWED_PERMISSION_PATHS = new Set([
  "permissions/me",
  "permissions/registry",
]);
const ALLOWED_MODULE_REGISTRY_PATHS = new Set([
  "modules/registry",
  "modules/me",
]);
const ALLOWED_MODULE_ADAPTER_REGISTRY_PATHS = new Set([
  "module-adapters/registry",
  "module-adapters/me",
]);
const ALLOWED_EXECUTION_PROVIDER_REGISTRY_PATHS = new Set([
  "execution-providers/registry",
  "execution-providers/me",
]);
const ALLOWED_EXTERNAL_DEPENDENCY_PATHS = new Set([
  "external-dependencies/registry",
  "external-dependencies/proposals",
  "external-dependencies/bindings",
  "external-dependencies/binding-rules",
  "external-dependencies/dependency-graph",
  "external-dependencies/binding-validation",
  "external-dependencies/binding-audit",
]);
const ALLOWED_AI_EXECUTION_BINDING_PATHS = new Set([
  "ai-execution-bindings/registry",
  "ai-execution-bindings/rules",
  "ai-execution-bindings/execution-flow",
  "ai-execution-bindings/validation",
  "ai-execution-bindings/ui-interaction",
  "ai-execution-bindings/completion-status",
]);
const ALLOWED_MODEL_LOCK_PATHS = new Set([
  "model-locks/registry",
  "model-locks/rules",
  "model-locks/enforcement",
  "model-locks/validation",
  "model-locks/request-validation",
  "model-locks/integration",
  "model-locks/completion-status",
]);
const ALLOWED_CAPABILITY_BINDING_PATHS = new Set([
  "capability-bindings/routing-model",
  "capability-bindings/model-mapping",
  "capability-bindings/module-bindings",
  "capability-bindings/enforcement",
  "capability-bindings/validation",
  "capability-bindings/request-validation",
  "capability-bindings/integration",
  "capability-bindings/completion-status",
]);
const ALLOWED_MODULE_WORKFLOW_BINDING_PATHS = new Set([
  "module-workflow-bindings/model",
  "module-workflow-bindings/enforcement",
  "module-workflow-bindings/access-control",
  "module-workflow-bindings/isolation-rules",
  "module-workflow-bindings/decision",
  "module-workflow-bindings/validation",
  "module-workflow-bindings/completion-status",
]);
const ALLOWED_MODULE_ALLOCATION_PATHS = new Set([
  "module-allocations/registry",
  "module-allocations/assignment-model",
  "module-allocations/categories",
  "module-allocations/budget-system",
  "module-allocations/enforcement",
  "module-allocations/integration-flow",
  "module-allocations/validation",
  "module-allocations/request-validation",
  "module-allocations/completion-status",
]);
const ALLOWED_EXECUTION_PROMPT_PATHS = new Set([
  "execution-prompts/template-engine",
  "execution-prompts/binding-injection",
  "execution-prompts/context-assembly",
  "execution-prompts/security-constraints",
  "execution-prompts/payload",
  "execution-prompts/validation",
  "execution-prompts/completion-status",
]);
const ALLOWED_PAYLOAD_STANDARDIZATION_GET_PATHS = new Set([
  "payload-standardization/model",
  "payload-standardization/normalization-engine",
  "payload-standardization/context-rules",
  "payload-standardization/workflow-mapping",
  "payload-standardization/completion-status",
]);
const ALLOWED_PAYLOAD_STANDARDIZATION_POST_PATHS = new Set([
  "payload-standardization/normalize",
]);
const ALLOWED_RESULT_NORMALIZATION_GET_PATHS = new Set([
  "result-normalization/normalization-engine",
  "result-normalization/schema-mapping",
  "result-normalization/module-adapters",
  "result-normalization/ui-output-structure",
  "result-normalization/completion-status",
]);
const ALLOWED_RESULT_NORMALIZATION_POST_PATHS = new Set([
  "result-normalization/normalize",
]);
const BLOCKED_SECURITY_ISOLATION_FIRST_SEGMENTS = new Set([
  "webhook",
  "n8n",
]);
const BLOCKED_SECURITY_ISOLATION_PATHS = new Set([
  "webhook-gateway/ingress",
]);

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

type HeadersWithSetCookie = Headers & {
  getSetCookie?: () => string[];
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

  if (
    parsedUrl.hostname.toLowerCase().includes("n8n") ||
    /\/(?:webhook|n8n)(?:\/|$)/i.test(parsedUrl.pathname)
  ) {
    throw new Error("Backend API URL must point to the Console backend.");
  }

  return parsedUrl;
}

function decodePathSegment(segment: string) {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

export function isBlockedSecurityIsolationPath(path: string[]) {
  const requestedPath = path.join("/");
  const firstSegment = path[0]?.toLowerCase();

  if (
    firstSegment &&
    BLOCKED_SECURITY_ISOLATION_FIRST_SEGMENTS.has(firstSegment)
  ) {
    return true;
  }

  if (BLOCKED_SECURITY_ISOLATION_PATHS.has(requestedPath)) {
    return true;
  }

  return path.some((segment) =>
    /^(?:https?:|n8n-webhook-ref:)/i.test(decodePathSegment(segment)),
  );
}

function isIntegerPathSegment(segment: string) {
  return /^[1-9]\d*$/.test(segment);
}

function isUuidPathSegment(segment: string) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    segment,
  );
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

function isAllowedPermissionPath(method: string, path: string[]) {
  const requestedPath = path.join("/");

  if (method === "GET" && ALLOWED_PERMISSION_PATHS.has(requestedPath)) {
    return true;
  }

  if (path[0] !== "permissions" || path[1] !== "users") {
    return false;
  }

  if (
    path.length === 4 &&
    isIntegerPathSegment(path[2]) &&
    path[3] === "assignments"
  ) {
    return method === "GET" || method === "POST";
  }

  if (
    path.length === 5 &&
    isIntegerPathSegment(path[2]) &&
    path[3] === "assignments" &&
    isUuidPathSegment(path[4])
  ) {
    return method === "PATCH" || method === "DELETE";
  }

  return false;
}

type BackendApiLayer = "public" | "app" | "control-plane";

function apiLayerPrefix(layer: BackendApiLayer) {
  if (layer === "public") {
    return PUBLIC_API_PREFIX;
  }
  if (layer === "app") {
    return APPLICATION_API_PREFIX;
  }
  return CONTROL_PLANE_API_PREFIX;
}

function withApiLayer(layer: BackendApiLayer, requestedPath: string) {
  return `${apiLayerPrefix(layer)}/${requestedPath}`;
}

export function getBackendApiPath(method: string, path: string[]) {
  const requestedPath = path.join("/");

  if (isBlockedSecurityIsolationPath(path)) {
    return null;
  }

  if (
    (method === "GET" && ALLOWED_PUBLIC_GET_PATHS.has(requestedPath)) ||
    (method === "POST" && ALLOWED_PUBLIC_POST_PATHS.has(requestedPath))
  ) {
    return withApiLayer("public", requestedPath);
  }

  if (
    (method === "GET" && ALLOWED_APP_LIST_PATHS.has(requestedPath)) ||
    isAllowedPermissionPath(method, path) ||
    isAllowedUsersPath(method, path)
  ) {
    return withApiLayer("app", requestedPath);
  }

  if (
    (method === "GET" && ALLOWED_CONTROL_PLANE_LIST_PATHS.has(requestedPath)) ||
    (method === "GET" && ALLOWED_MODULE_REGISTRY_PATHS.has(requestedPath)) ||
    (method === "GET" &&
      ALLOWED_MODULE_ADAPTER_REGISTRY_PATHS.has(requestedPath)) ||
    (method === "GET" &&
      ALLOWED_EXECUTION_PROVIDER_REGISTRY_PATHS.has(requestedPath)) ||
    (method === "GET" &&
      ALLOWED_EXTERNAL_DEPENDENCY_PATHS.has(requestedPath)) ||
    (method === "GET" &&
      ALLOWED_AI_EXECUTION_BINDING_PATHS.has(requestedPath)) ||
    (method === "GET" && ALLOWED_MODEL_LOCK_PATHS.has(requestedPath)) ||
    (method === "GET" &&
      ALLOWED_CAPABILITY_BINDING_PATHS.has(requestedPath)) ||
    (method === "GET" &&
      ALLOWED_MODULE_WORKFLOW_BINDING_PATHS.has(requestedPath)) ||
    (method === "GET" &&
      ALLOWED_MODULE_ALLOCATION_PATHS.has(requestedPath)) ||
    (method === "GET" &&
      ALLOWED_EXECUTION_PROMPT_PATHS.has(requestedPath)) ||
    (method === "GET" &&
      ALLOWED_PAYLOAD_STANDARDIZATION_GET_PATHS.has(requestedPath)) ||
    (method === "POST" &&
      ALLOWED_PAYLOAD_STANDARDIZATION_POST_PATHS.has(requestedPath)) ||
    (method === "GET" &&
      ALLOWED_RESULT_NORMALIZATION_GET_PATHS.has(requestedPath)) ||
    (method === "POST" &&
      ALLOWED_RESULT_NORMALIZATION_POST_PATHS.has(requestedPath)) ||
    (process.env.NODE_ENV !== "production" &&
      process.env.NEXT_PUBLIC_ENABLE_INTERNAL_DIAGNOSTICS === "true" &&
      method === "GET" &&
      requestedPath === "n8n-test/latest")
  ) {
    return withApiLayer("control-plane", requestedPath);
  }

  return null;
}

export function isAllowedBackendProxyPath(method: string, path: string[]) {
  return getBackendApiPath(method, path) !== null;
}

function getSetCookieHeaders(headers: Headers) {
  const getSetCookie = (headers as HeadersWithSetCookie).getSetCookie;
  if (typeof getSetCookie === "function") {
    return getSetCookie.call(headers);
  }

  const setCookie = headers.get("set-cookie");
  return setCookie ? [setCookie] : [];
}

async function proxyRequest(
  request: NextRequest,
  context: RouteContext,
) {
  const { path } = await context.params;
  const backendApiPath = getBackendApiPath(request.method, path);

  if (isBlockedSecurityIsolationPath(path)) {
    return Response.json({ detail: "Not found." }, { status: 404 });
  }

  if (backendApiPath === null) {
    return Response.json({ detail: "Not found." }, { status: 404 });
  }

  try {
    const targetUrl = new URL(backendApiPath, getApiBaseUrl());
    targetUrl.search = request.nextUrl.search;
    const headers = new Headers({
      Accept: "application/json",
    });
    const cookie = request.headers.get("cookie");
    const contentType = request.headers.get("content-type");

    if (cookie) {
      headers.set("Cookie", cookie);
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
    const setCookies = getSetCookieHeaders(backendResponse.headers);

    if (backendContentType) {
      responseHeaders.set("Content-Type", backendContentType);
    }
    if (authenticate) {
      responseHeaders.set("WWW-Authenticate", authenticate);
    }
    for (const setCookie of setCookies) {
      responseHeaders.append("Set-Cookie", setCookie);
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

export function DELETE(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}
