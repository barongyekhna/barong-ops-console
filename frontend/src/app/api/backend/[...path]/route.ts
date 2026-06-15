import type { NextRequest } from "next/server";

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

export function isAllowedBackendProxyPath(method: string, path: string[]) {
  const requestedPath = path.join("/");

  return (
    (method === "GET" && requestedPath === "health") ||
    ALLOWED_AUTH_PATHS.has(requestedPath) ||
    (method === "GET" && ALLOWED_LIST_PATHS.has(requestedPath)) ||
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
    isAllowedPermissionPath(method, path) ||
    (method === "POST" && requestedPath === "foundation-demo/run") ||
    (method === "GET" && requestedPath === "foundation-demo/latest") ||
    (method === "POST" && requestedPath === "n8n-test/run") ||
    (method === "GET" && requestedPath === "n8n-test/latest") ||
    isAllowedUsersPath(method, path)
  );
}

async function proxyRequest(
  request: NextRequest,
  context: RouteContext,
) {
  const { path } = await context.params;
  const requestedPath = path.join("/");

  if (!isAllowedBackendProxyPath(request.method, path)) {
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

export function DELETE(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}
