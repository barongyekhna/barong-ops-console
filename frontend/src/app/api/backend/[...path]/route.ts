import type { NextRequest } from "next/server";

const PUBLIC_API_PREFIX = "/api/public";
const APPLICATION_API_PREFIX = "/api/app";
const CONTROL_PLANE_API_PREFIX = "/api/control-plane";
const SESSION_TOKEN_HEADER = "x-session-token";
const FRONTEND_FORCE_REFRESH_HEADER = "x-frontend-force-refresh";

const ALLOWED_PUBLIC_GET_PATHS = new Set([
  "health",
  "auth/context",
  "auth/me",
]);
const ALLOWED_PUBLIC_POST_PATHS = new Set([
  "auth/change-password",
  "auth/login",
  "auth/logout",
]);
const ALLOWED_APP_LIST_PATHS = new Set([
  "dashboard/activity",
  "dashboard/overview",
  "reviews",
  "errors",
  "memory-events",
  "operation-logs",
  "organizations",
  "approval/list",
  "approvals/list",
]);
const ALLOWED_CONTROL_PLANE_LIST_PATHS = new Set([
  "modules",
  "agents",
]);
const ALLOWED_APP_RESOURCE_PATHS = new Set([
  "context-packets",
  "errors",
  "memory-events",
  "memory-summaries",
]);
const ALLOWED_APP_CREATE_RESOURCE_PATHS = new Set([
  "context-packets",
  "errors",
  "memory-events",
]);
const ALLOWED_CONTROL_PLANE_RESOURCE_PATHS = new Set([
  "agents",
  "modules",
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
const ALLOWED_MODULE_CONTROL_GET_PATHS = new Set([
  "module-control/center",
]);
const ALLOWED_MODULE_ADAPTER_REGISTRY_PATHS = new Set([
  "module-adapters/registry",
  "module-adapters/me",
]);
const ALLOWED_EXECUTION_PROVIDER_REGISTRY_PATHS = new Set([
  "execution-providers/registry",
  "execution-providers/me",
]);
const ALLOWED_LIVE_GATE_GET_PATHS = new Set([
  "live-gate/readiness",
  "live-gate/production-readiness",
  "live-gate/policies",
]);
const CAPABILITY_BOOTSTRAP_PATH = "capability/bootstrap";
const CAPABILITY_BOOTSTRAP_BACKEND_PATH = `${CONTROL_PLANE_API_PREFIX}/${CAPABILITY_BOOTSTRAP_PATH}`;
const CAPABILITY_BOOTSTRAP_CACHE_TTL_MS = 60_000;
const CAPABILITY_BOOTSTRAP_MAX_BACKEND_CONCURRENCY = 6;
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
const ALLOWED_N8N_WEBHOOK_TEST_POST_PATHS = new Set([
  "n8n-webhook-test/run",
]);
const API_KEY_ID_PATTERN = /^(?:key|akb)_[0-9a-f]{32}$/;
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

type CapabilityBootstrapEntry = {
  ok: boolean;
  status: number;
  data: unknown;
  detail: unknown;
};

type CapabilityBootstrapTarget = {
  key: string;
  path: string[];
};

const capabilityBootstrapTargets: CapabilityBootstrapTarget[] = [
  { key: "modules_registry", path: ["modules", "registry"] },
  { key: "modules_me", path: ["modules", "me"] },
  { key: "module_control_center", path: ["module-control", "center"] },
  {
    key: "module_adapters_registry",
    path: ["module-adapters", "registry"],
  },
  { key: "module_adapters_me", path: ["module-adapters", "me"] },
  {
    key: "execution_providers_registry",
    path: ["execution-providers", "registry"],
  },
  { key: "execution_providers_me", path: ["execution-providers", "me"] },
  { key: "live_gate_readiness", path: ["live-gate", "readiness"] },
  {
    key: "live_gate_production_readiness",
    path: ["live-gate", "production-readiness"],
  },
  { key: "live_gate_policies", path: ["live-gate", "policies"] },
];

const capabilityBootstrapCache = new Map<
  string,
  { expiresAt: number; payload: Record<string, CapabilityBootstrapEntry> }
>();
const capabilityBootstrapInFlight = new Map<
  string,
  Promise<Record<string, CapabilityBootstrapEntry>>
>();
let capabilityBootstrapCacheGeneration = 0;

function clearCapabilityBootstrapCache(cacheKey: string | null = null) {
  capabilityBootstrapCacheGeneration += 1;
  if (cacheKey) {
    capabilityBootstrapCache.delete(cacheKey);
    capabilityBootstrapInFlight.delete(cacheKey);
    return;
  }
  capabilityBootstrapCache.clear();
  capabilityBootstrapInFlight.clear();
}

function isFrontendForceRefreshRequest(request: NextRequest) {
  return (
    request.headers.get(FRONTEND_FORCE_REFRESH_HEADER) === "1" ||
    request.nextUrl.searchParams.get("force_refresh") === "1" ||
    request.nextUrl.searchParams.get("_force_refresh") === "1"
  );
}

function applySessionHeaders(headers: Headers, request: NextRequest) {
  const cookie = request.headers.get("cookie");
  const sessionToken = request.headers.get(SESSION_TOKEN_HEADER);

  if (cookie) {
    headers.set("Cookie", cookie);
  }
  if (sessionToken) {
    headers.set("X-Session-Token", sessionToken);
  }
}

function applyForceRefreshHeaders(headers: Headers, request: NextRequest) {
  if (isFrontendForceRefreshRequest(request)) {
    headers.set(FRONTEND_FORCE_REFRESH_HEADER, "1");
  }
}

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

function isAllowedAppResourcePath(method: string, path: string[]) {
  const resource = path[0];

  if (!ALLOWED_APP_RESOURCE_PATHS.has(resource)) {
    return false;
  }

  if (path.length === 1) {
    return (
      method === "GET" ||
      (method === "POST" && ALLOWED_APP_CREATE_RESOURCE_PATHS.has(resource))
    );
  }

  if (path.length === 2) {
    return method === "GET";
  }

  return false;
}

function isAllowedReviewAuditPath(method: string, path: string[]) {
  if (method !== "GET" || path[0] !== "reviews") {
    return false;
  }

  if (path.length === 2 && path[1] === "module-registry") {
    return true;
  }

  if (path[1] !== "organizations") {
    return false;
  }

  if (path.length === 2) {
    return true;
  }

  if (path.length === 4 && path[3] === "users") {
    return true;
  }

  if (
    path.length === 6 &&
    path[3] === "users" &&
    isIntegerPathSegment(path[4]) &&
    path[5] === "actions"
  ) {
    return true;
  }

  return false;
}

function isAllowedApprovalPath(method: string, path: string[]) {
  if (path[0] !== "approval") {
    return false;
  }

  if (path.length === 2 && path[1] === "list") {
    return method === "GET";
  }

  if (path.length === 2 && path[1] === "request") {
    return method === "POST";
  }

  if (path.length === 2) {
    return method === "GET";
  }

  if (
    path.length === 3 &&
    (path[2] === "approve" || path[2] === "reject")
  ) {
    return method === "POST";
  }

  return false;
}

function isAllowedOrgPath(method: string, path: string[]) {
  if (path[0] !== "org") {
    return false;
  }

  if (path.length === 2 && path[1] === "create") {
    return method === "POST";
  }

  if (path.length === 2) {
    return method === "PATCH" || method === "DELETE";
  }

  if (
    path.length === 3 &&
    (path[2] === "activate" || path[2] === "suspend")
  ) {
    return method === "POST";
  }

  if (path.length === 3 && path[2] === "members") {
    return method === "GET";
  }

  if (
    path.length === 4 &&
    path[2] === "members" &&
    (path[3] === "add" || path[3] === "remove")
  ) {
    return method === "POST";
  }

  return false;
}

function isAllowedControlPlaneResourcePath(method: string, path: string[]) {
  const resource = path[0];

  if (!ALLOWED_CONTROL_PLANE_RESOURCE_PATHS.has(resource)) {
    return false;
  }

  if (path.length === 1) {
    return method === "GET" || method === "POST";
  }

  if (path.length === 2) {
    return method === "GET";
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

function isAllowedModuleControlPath(method: string, path: string[]) {
  if (method === "GET" && ALLOWED_MODULE_CONTROL_GET_PATHS.has(path.join("/"))) {
    return true;
  }

  return (
    method === "PATCH" &&
    path.length === 5 &&
    path[0] === "module-control" &&
    path[1] === "organizations" &&
    path[3] === "registry-entries" &&
    path[2].startsWith("org_") &&
    path[4].includes(".")
  );
}

function isAllowedApiKeyOrchestrationPath(method: string, path: string[]) {
  if (path[0] !== "api-key-orchestration") {
    return false;
  }

  if (path.length === 2 && path[1] === "keys") {
    return method === "GET";
  }

  if (
    path.length === 3 &&
    path[1] === "keys" &&
    API_KEY_ID_PATTERN.test(path[2])
  ) {
    return method === "PATCH" || method === "DELETE";
  }

  if (path.length === 2 && path[1] === "bindings") {
    return method === "GET";
  }

  if (
    path.length === 4 &&
    path[1] === "organizations" &&
    path[2].startsWith("org_") &&
    (path[3] === "keys" || path[3] === "bindings")
  ) {
    return method === "POST";
  }

  if (
    path.length === 3 &&
    path[1] === "bindings" &&
    API_KEY_ID_PATTERN.test(path[2])
  ) {
    return method === "DELETE";
  }

  return false;
}

function isAllowedNotificationsPath(method: string, path: string[]) {
  if (path[0] !== "notifications") {
    return false;
  }
  // GET /notifications  (list, with optional query string)
  if (path.length === 1) {
    return method === "GET";
  }
  // GET /notifications/unread-count
  if (path.length === 2 && path[1] === "unread-count") {
    return method === "GET";
  }
  // POST /notifications/read-all
  if (path.length === 2 && path[1] === "read-all") {
    return method === "POST";
  }
  // POST /notifications/{id}/read
  if (path.length === 3 && path[2] === "read") {
    return method === "POST";
  }
  // NB: /notifications/ingest is intentionally NOT proxied (server-to-server).
  return false;
}

function isAllowedKPath(method: string, path: string[]) {
  if (path[0] !== "k") {
    return false;
  }

  if (path.length === 2 && path[1] === "products") {
    return method === "GET" || method === "POST";
  }

  if (
    path.length === 3 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2])
  ) {
    return method === "GET" || method === "PATCH" || method === "DELETE";
  }

  if (
    path.length === 4 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "archive"
  ) {
    return method === "POST";
  }

  if (
    path.length === 4 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    ["attributes", "keywords", "risk-terms"].includes(path[3])
  ) {
    return method === "GET" || method === "PATCH";
  }

  if (
    path.length === 4 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    ["readiness", "selling-points"].includes(path[3])
  ) {
    return method === "GET";
  }

  if (
    path.length === 4 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    ["generate-copy", "generate-image-brief"].includes(path[3])
  ) {
    return method === "POST";
  }

  if (
    path.length === 4 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "generation-jobs"
  ) {
    return method === "GET";
  }

  if (
    path.length === 4 &&
    path[1] === "products" &&
    ["generate-copy", "generate-image-brief"].includes(path[2]) &&
    path[3] === "batch"
  ) {
    return method === "POST";
  }

  if (
    path.length === 2 &&
    ["keywords", "risks", "risk", "media"].includes(path[1])
  ) {
    return method === "GET" || method === "POST";
  }

  if (
    path.length === 3 &&
    ["keywords", "risks", "risk"].includes(path[1])
  ) {
    if (path[1] === "keywords" && method === "GET") {
      return true;
    }
    return (
      isUuidPathSegment(path[2]) &&
      (method === "PATCH" || method === "DELETE")
    );
  }

  if (
    path.length === 3 &&
    path[1] === "media" &&
    isUuidPathSegment(path[2])
  ) {
    return method === "DELETE";
  }

  if (
    path.length === 4 &&
    path[1] === "media" &&
    isUuidPathSegment(path[2]) &&
    ["download", "file", "thumbnail", "preview"].includes(path[3])
  ) {
    return method === "GET";
  }

  if (
    path.length === 3 &&
    path[1] === "keyword-research" &&
    path[2] === "start"
  ) {
    return method === "POST";
  }

  if (path.length === 2 && path[1] === "research") {
    return method === "POST";
  }

  if (path.length === 3 && path[1] === "serp" && path[2] === "search") {
    return method === "POST";
  }

  if (
    path.length === 3 &&
    path[1] === "selling-points" &&
    path[2] === "generate"
  ) {
    return method === "POST";
  }

  if (
    path.length === 5 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "selling-points" &&
    ["generate", "approve"].includes(path[4])
  ) {
    return method === "POST";
  }

  if (
    path.length === 5 &&
    path[1] === "products" &&
    path[3] === "enrich" &&
    path[4] === "deepseek"
  ) {
    return method === "POST";
  }

  if (
    path.length === 5 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "media" &&
    path[4] === "upload"
  ) {
    return method === "POST";
  }

  if (
    path.length === 4 &&
    path[1] === "products" &&
    ["translate", "risk-filter"].includes(path[3])
  ) {
    return method === "POST";
  }

  if (
    path.length === 5 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "keywords" &&
    path[4] === "submit"
  ) {
    return method === "POST";
  }

  if (
    path.length === 5 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "workflow" &&
    [
      "latest",
      "start",
      "risk-review",
      "export",
      "pause",
      "resume",
      "retry",
      "rollback",
    ].includes(path[4])
  ) {
    return path[4] === "latest" ? method === "GET" : method === "POST";
  }

  if (
    path.length === 5 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "images" &&
    ["bind", "submit", "import-i-output"].includes(path[4])
  ) {
    return method === "POST";
  }

  return false;
}

function isAllowedIPath(method: string, path: string[]) {
  if (path[0] !== "i") {
    return false;
  }

  if (
    path.length === 3 &&
    path[1] === "prompts" &&
    path[2] === "transform"
  ) {
    return method === "POST";
  }

  if (
    path.length === 3 &&
    path[1] === "images" &&
    ["generate", "edit"].includes(path[2])
  ) {
    return method === "POST";
  }

  if (path.length === 2 && path[1] === "media-library") {
    return method === "GET" || method === "POST";
  }

  if (
    path.length === 3 &&
    path[1] === "media-library" &&
    isUuidPathSegment(path[2])
  ) {
    return method === "DELETE";
  }

  if (
    path.length === 4 &&
    path[1] === "media-library" &&
    isUuidPathSegment(path[2]) &&
    ["file", "thumbnail", "preview"].includes(path[3])
  ) {
    return method === "GET";
  }

  return false;
}

function isAllowedRPath(method: string, path: string[]) {
  if (path[0] !== "r") {
    return false;
  }

  if (path[1] === "analysis") {
    if (
      method === "GET" &&
      path.length === 3 &&
      ["framework", "status"].includes(path[2])
    ) {
      return true;
    }

    if (
      method === "GET" &&
      path.length === 4 &&
      path[2] === "profit" &&
      ["config", "snapshots"].includes(path[3])
    ) {
      return true;
    }

    if (
      method === "POST" &&
      path.length === 4 &&
      path[2] === "profit" &&
      ["manual", "run", "auto-run"].includes(path[3])
    ) {
      return true;
    }

    if (
      method === "POST" &&
      path.length === 3 &&
      path[2] === "supplier-search"
    ) {
      return true;
    }

    if (
      method === "POST" &&
      path.length === 4 &&
      path[2] === "profit" &&
      path[3] === "jobs"
    ) {
      return true;
    }

    if (
      method === "GET" &&
      path.length === 5 &&
      path[2] === "profit" &&
      path[3] === "jobs" &&
      (isUuidPathSegment(path[4]) || path[4] === "latest")
    ) {
      return true;
    }
  }

  if (path.length === 3 && path[1] === "commerce") {
    if (["skills", "report"].includes(path[2])) {
      return method === "GET";
    }
    if (["run", "review"].includes(path[2])) {
      return method === "POST";
    }
  }

  return false;
}

function isAllowedRwPath(method: string, path: string[]) {
  if (path[0] !== "rw") {
    return false;
  }

  return (
    method === "GET" &&
    path.length === 2 &&
    ["products", "status", "rules", "category-tree", "category-rate-plan", "pipeline", "settings"].includes(path[1])
  ) || (
    method === "POST" &&
    path.length === 2 &&
    path[1] === "settings"
  ) || (
    method === "DELETE" &&
    path.length === 2 &&
    path[1] === "products-rejected"
  ) || (
    method === "DELETE" &&
    path.length === 3 &&
    path[1] === "products"
  ) || (
    method === "POST" &&
    path.length === 3 &&
    path[1] === "category-tree" &&
    ["select", "save"].includes(path[2])
  );
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

  if (method === "GET" && requestedPath === CAPABILITY_BOOTSTRAP_PATH) {
    return CAPABILITY_BOOTSTRAP_PATH;
  }

  if (
    (method === "GET" && ALLOWED_PUBLIC_GET_PATHS.has(requestedPath)) ||
    (method === "POST" && ALLOWED_PUBLIC_POST_PATHS.has(requestedPath))
  ) {
    return withApiLayer("public", requestedPath);
  }

  if (
    (method === "GET" && ALLOWED_APP_LIST_PATHS.has(requestedPath)) ||
    isAllowedReviewAuditPath(method, path) ||
    isAllowedAppResourcePath(method, path) ||
    isAllowedApprovalPath(method, path) ||
    isAllowedOrgPath(method, path) ||
    isAllowedPermissionPath(method, path) ||
    isAllowedUsersPath(method, path) ||
    isAllowedKPath(method, path) ||
    isAllowedIPath(method, path) ||
    isAllowedRPath(method, path) ||
    isAllowedRwPath(method, path) ||
    isAllowedNotificationsPath(method, path)
  ) {
    return withApiLayer("app", requestedPath);
  }

  if (
    (method === "GET" && ALLOWED_CONTROL_PLANE_LIST_PATHS.has(requestedPath)) ||
    isAllowedControlPlaneResourcePath(method, path) ||
    (method === "GET" && ALLOWED_MODULE_REGISTRY_PATHS.has(requestedPath)) ||
    isAllowedModuleControlPath(method, path) ||
    isAllowedApiKeyOrchestrationPath(method, path) ||
    (method === "GET" &&
      ALLOWED_MODULE_ADAPTER_REGISTRY_PATHS.has(requestedPath)) ||
    (method === "GET" &&
      ALLOWED_EXECUTION_PROVIDER_REGISTRY_PATHS.has(requestedPath)) ||
    (method === "GET" && ALLOWED_LIVE_GATE_GET_PATHS.has(requestedPath)) ||
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
    (method === "POST" &&
      ALLOWED_N8N_WEBHOOK_TEST_POST_PATHS.has(requestedPath))
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
  const requestedPath = path.join("/");

  if (request.method === "GET" && requestedPath === CAPABILITY_BOOTSTRAP_PATH) {
    return capabilityBootstrapRequest(request);
  }

  const backendApiPath = getBackendApiPath(request.method, path);

  if (isBlockedSecurityIsolationPath(path)) {
    return Response.json({ detail: "暂无数据。" }, { status: 404 });
  }

  if (backendApiPath === null) {
    return Response.json({ detail: "暂无数据。" }, { status: 404 });
  }

  try {
    const targetUrl = new URL(backendApiPath, getApiBaseUrl());
    targetUrl.search = request.nextUrl.search;
    const headers = new Headers({
      Accept: request.headers.get("accept") || "application/json",
    });
    const contentType = request.headers.get("content-type");
    const idempotencyKey = request.headers.get("idempotency-key");

    applySessionHeaders(headers, request);
    applyForceRefreshHeaders(headers, request);
    if (contentType) {
      headers.set("Content-Type", contentType);
    }
    if (idempotencyKey) {
      headers.set("Idempotency-Key", idempotencyKey);
    }

    const requestBody =
      request.method === "GET" ? undefined : await request.arrayBuffer();
    const backendResponse = await fetch(targetUrl, {
      body:
        requestBody && requestBody.byteLength > 0
          ? requestBody
          : undefined,
      cache: "no-store",
      headers,
      method: request.method,
      signal: request.signal,
    });
    const responseHeaders = new Headers();
    const backendContentType = backendResponse.headers.get("content-type");
    const authenticate = backendResponse.headers.get("www-authenticate");
    const setCookies = getSetCookieHeaders(backendResponse.headers);

    if (backendContentType) {
      responseHeaders.set("Content-Type", backendContentType);
    }
    for (const headerName of [
      "accept-ranges",
      "cache-control",
      "content-disposition",
      "content-length",
      "etag",
      "last-modified",
    ]) {
      const headerValue = backendResponse.headers.get(headerName);
      if (headerValue) {
        responseHeaders.set(headerName, headerValue);
      }
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
      { detail: "服务暂时不可用，请稍后再试。" },
      { status: 503 },
    );
  }
}

function getCapabilityBootstrapCacheKey(request: NextRequest) {
  const cookie = request.headers.get("cookie") ?? "";
  const sessionToken = request.headers.get(SESSION_TOKEN_HEADER) ?? "";
  return `cookie:${cookie}|token:${sessionToken}`;
}

function readCapabilityBootstrapCache(cacheKey: string) {
  const cached = capabilityBootstrapCache.get(cacheKey);

  if (!cached) {
    return null;
  }

  if (cached.expiresAt <= Date.now()) {
    capabilityBootstrapCache.delete(cacheKey);
    return null;
  }

  return cached.payload;
}

async function readBackendJson(response: Response) {
  try {
    const text = await response.text();
    if (text.trim().length === 0) {
      return null;
    }
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  } catch {
    return null;
  }
}

async function fetchCapabilityBootstrapTarget(
  target: CapabilityBootstrapTarget,
  request: NextRequest,
): Promise<[string, CapabilityBootstrapEntry]> {
  const backendApiPath = getBackendApiPath("GET", target.path);
  if (backendApiPath === null || backendApiPath === CAPABILITY_BOOTSTRAP_PATH) {
    return [
      target.key,
      {
        data: null,
        detail: "服务暂时不可用，请稍后再试。",
        ok: false,
        status: 404,
      },
    ];
  }

  try {
    const targetUrl = new URL(backendApiPath, getApiBaseUrl());
    const headers = new Headers({ Accept: "application/json" });

    applySessionHeaders(headers, request);
    applyForceRefreshHeaders(headers, request);
    if (isFrontendForceRefreshRequest(request)) {
      targetUrl.searchParams.set("force_refresh", "1");
    }

    const backendResponse = await fetch(targetUrl, {
      cache: "no-store",
      headers,
      method: "GET",
      signal: request.signal,
    });
    const payload = await readBackendJson(backendResponse);

    return [
      target.key,
      {
        data: backendResponse.ok ? payload : null,
        detail: backendResponse.ok ? null : payload,
        ok: backendResponse.ok,
        status: backendResponse.status,
      },
    ];
  } catch {
    return [
      target.key,
      {
        data: null,
        detail: "服务暂时不可用，请稍后再试。",
        ok: false,
        status: 503,
      },
    ];
  }
}

async function runCapabilityBootstrapTargets(request: NextRequest) {
  const payload: Record<string, CapabilityBootstrapEntry> = {};
  let nextIndex = 0;

  async function worker() {
    while (nextIndex < capabilityBootstrapTargets.length) {
      const target = capabilityBootstrapTargets[nextIndex];
      nextIndex += 1;
      const [key, entry] = await fetchCapabilityBootstrapTarget(
        target,
        request,
      );
      payload[key] = entry;
    }
  }

  await Promise.all(
    Array.from(
      {
        length: Math.min(
          CAPABILITY_BOOTSTRAP_MAX_BACKEND_CONCURRENCY,
          capabilityBootstrapTargets.length,
        ),
      },
      () => worker(),
    ),
  );

  return payload;
}

async function fetchCapabilityBootstrapBatch(
  request: NextRequest,
): Promise<Record<string, CapabilityBootstrapEntry> | null> {
  try {
    const targetUrl = new URL(CAPABILITY_BOOTSTRAP_BACKEND_PATH, getApiBaseUrl());
    const headers = new Headers({ Accept: "application/json" });

    applySessionHeaders(headers, request);
    applyForceRefreshHeaders(headers, request);
    if (isFrontendForceRefreshRequest(request)) {
      targetUrl.searchParams.set("force_refresh", "1");
    }

    const backendResponse = await fetch(targetUrl, {
      cache: "no-store",
      headers,
      method: "GET",
      signal: request.signal,
    });
    if (!backendResponse.ok) {
      return null;
    }

    const payload = await readBackendJson(backendResponse);
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return null;
    }

    return payload as Record<string, CapabilityBootstrapEntry>;
  } catch {
    return null;
  }
}

async function capabilityBootstrapRequest(request: NextRequest) {
  const cacheKey = getCapabilityBootstrapCacheKey(request);
  const forceRefresh = isFrontendForceRefreshRequest(request);

  if (forceRefresh) {
    clearCapabilityBootstrapCache(cacheKey);
  }

  const cached = forceRefresh ? null : readCapabilityBootstrapCache(cacheKey);

  if (cached) {
    return Response.json(cached);
  }

  const inFlight = forceRefresh ? null : capabilityBootstrapInFlight.get(cacheKey);
  if (inFlight) {
    return Response.json(await inFlight);
  }

  const requestCacheGeneration = capabilityBootstrapCacheGeneration;
  const promise = (async () => {
    const batched = await fetchCapabilityBootstrapBatch(request);
    if (batched) {
      return batched;
    }

    return runCapabilityBootstrapTargets(request);
  })().finally(() => {
    capabilityBootstrapInFlight.delete(cacheKey);
  });
  capabilityBootstrapInFlight.set(cacheKey, promise);

  const payload = await promise;
  if (requestCacheGeneration === capabilityBootstrapCacheGeneration) {
    capabilityBootstrapCache.set(cacheKey, {
      expiresAt: Date.now() + CAPABILITY_BOOTSTRAP_CACHE_TTL_MS,
      payload,
    });
  }

  return Response.json(payload);
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
