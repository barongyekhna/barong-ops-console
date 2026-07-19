import { isIP } from "node:net";

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
const ALLOWED_ARCADE_GAME_IDS = new Set([
  "shmup",
  "snake",
  "tetris",
  "tank",
  "asteroids",
  "breakout",
  "2048",
  "runner",
  "match3",
  "mines",
  "flappy",
  "pong",
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
const API_KEY_ID_PATTERN = /^(?:key|akb)_[0-9a-f]{32}$/;
const BLOCKED_SECURITY_ISOLATION_FIRST_SEGMENTS = new Set([
  "webhook",
  "n8n",
]);
const BLOCKED_SECURITY_ISOLATION_PATHS = new Set([
  "webhook-gateway/ingress",
]);
const BLOCKED_C19_INFRASTRUCTURE_SEGMENTS = new Set([
  "adapter",
  "adapters",
  "asset-store",
  "chat-asset-store",
  "chat-record-store",
  "config",
  "configuration",
  "credential",
  "credentials",
  "endpoint",
  "endpoints",
  "provider",
  "providers",
  "record-store",
  "secret",
  "secrets",
  "storage",
  "storages",
  "vps",
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

export function normalizeTrustedClientIp(value: string | null) {
  if (!value || value !== value.trim() || value.includes(",")) return null;
  return isIP(value) === 0 ? null : value;
}

export function applyTrustedClientIp(
  headers: Headers,
  sourceHeaders: Pick<Headers, "get">,
) {
  // The public Nginx entrypoint overwrites X-Real-IP with $remote_addr. Never
  // copy the browser-controlled X-Forwarded-For chain through this proxy.
  headers.delete("X-Forwarded-For");
  const clientIp = normalizeTrustedClientIp(sourceHeaders.get("x-real-ip"));
  if (clientIp) headers.set("X-Forwarded-For", clientIp);
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

  if (isBlockedC19InfrastructurePath(path)) {
    return true;
  }

  return path.some((segment) =>
    /^(?:https?:|n8n-webhook-ref:)/i.test(decodePathSegment(segment)),
  );
}

export function isBlockedC19InfrastructurePath(path: string[]) {
  if (path[0]?.toLowerCase() !== "c19") {
    return false;
  }

  return path.slice(1).some((segment) =>
    BLOCKED_C19_INFRASTRUCTURE_SEGMENTS.has(
      decodePathSegment(segment).trim().toLowerCase(),
    ),
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

function isC19FriendRequestId(segment: string | undefined) {
  return Boolean(segment && /^c19frq_[0-9a-f]{32}$/.test(segment));
}

function isC19ConversationId(segment: string | undefined) {
  return Boolean(segment && /^conv_[0-9a-f]{32}$/.test(segment));
}

function isC19AssetId(segment: string | undefined) {
  return Boolean(segment && /^att_[0-9a-f]{32}$/.test(segment));
}

function isC19MomentId(segment: string | undefined) {
  return Boolean(segment && /^mom_[0-9a-f]{32}$/.test(segment));
}

function isC19MomentCommentId(segment: string | undefined) {
  return Boolean(segment && /^cmt_[0-9a-f]{32}$/.test(segment));
}

function isC19RecordId(segment: string | undefined) {
  return Boolean(segment && /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(segment));
}

export function isAllowedC19Path(method: string, path: string[]) {
  if (
    path[0] !== "c19" ||
    path.length < 2 ||
    isBlockedC19InfrastructurePath(path)
  ) {
    return false;
  }

  const resource = path[1];

  if (method === "GET" && path.length === 2 && resource === "unread") {
    return true;
  }

  if (method === "GET" && path.length === 2 && resource === "events") {
    return true;
  }

  if (
    method === "GET" &&
    path.length === 3 &&
    resource === "events" &&
    path[2] === "tail"
  ) {
    return true;
  }

  if (
    method === "PATCH" &&
    path.length === 3 &&
    resource === "profiles" &&
    path[2] === "me"
  ) {
    return true;
  }

  if (resource === "moments") {
    if (
      path.length === 3 &&
      ((method === "POST" && path[2] === "drafts") ||
        (method === "GET" && ["events", "feed"].includes(path[2])))
    ) {
      return true;
    }

    if (
      method === "GET" &&
      path.length === 4 &&
      path[2] === "events" &&
      path[3] === "tail"
    ) {
      return true;
    }

    if (path.length === 3 && isC19MomentId(path[2])) {
      return method === "GET" || method === "DELETE";
    }

    if (
      path.length === 4 &&
      isC19MomentId(path[2]) &&
      path[3] === "publish"
    ) {
      return method === "POST";
    }

    if (
      path.length === 4 &&
      isC19MomentId(path[2]) &&
      path[3] === "like"
    ) {
      return method === "PUT" || method === "DELETE";
    }

    if (
      path.length === 4 &&
      isC19MomentId(path[2]) &&
      path[3] === "likes"
    ) {
      return method === "GET";
    }

    if (
      path.length === 4 &&
      isC19MomentId(path[2]) &&
      path[3] === "comments"
    ) {
      return method === "GET" || method === "POST";
    }

    if (
      path.length === 5 &&
      isC19MomentId(path[2]) &&
      path[3] === "comments" &&
      isC19MomentCommentId(path[4])
    ) {
      return method === "DELETE";
    }

    if (
      method === "POST" &&
      path.length === 5 &&
      isC19MomentId(path[2]) &&
      path[3] === "assets" &&
      path[4] === "upload-intents"
    ) {
      return true;
    }

    if (
      path.length === 5 &&
      isC19MomentId(path[2]) &&
      path[3] === "assets" &&
      isC19AssetId(path[4])
    ) {
      return method === "GET";
    }

    if (
      method === "POST" &&
      path.length === 6 &&
      isC19MomentId(path[2]) &&
      path[3] === "assets" &&
      isC19AssetId(path[4]) &&
      ["access-intents", "finalize"].includes(path[5])
    ) {
      return true;
    }
  }

  if (
    method === "GET" &&
    path.length === 2 &&
    ["blocks", "conversations", "directory", "friend-requests", "friends"].includes(
      resource,
    )
  ) {
    return true;
  }

  if (
    method === "GET" &&
    path.length === 3 &&
    resource === "profiles" &&
    isIntegerPathSegment(path[2])
  ) {
    return true;
  }

  if (
    method === "POST" &&
    path.length === 2 &&
    (resource === "friend-requests" || resource === "groups")
  ) {
    return true;
  }

  if (
    method === "POST" &&
    path.length === 4 &&
    resource === "friend-requests" &&
    isC19FriendRequestId(path[2]) &&
    ["accept", "cancel", "reject"].includes(path[3])
  ) {
    return true;
  }

  if (
    path.length === 3 &&
    resource === "friends" &&
    isIntegerPathSegment(path[2])
  ) {
    return method === "DELETE";
  }

  if (
    path.length === 3 &&
    resource === "blocks" &&
    isIntegerPathSegment(path[2])
  ) {
    return method === "POST" || method === "DELETE";
  }

  if (
    method === "POST" &&
    path.length === 3 &&
    resource === "conversations" &&
    path[2] === "direct"
  ) {
    return true;
  }

  if (
    method === "GET" &&
    path.length === 3 &&
    resource === "conversations" &&
    isC19ConversationId(path[2])
  ) {
    return true;
  }

  if (
    path.length === 4 &&
    resource === "conversations" &&
    isC19ConversationId(path[2]) &&
    path[3] === "settings"
  ) {
    return method === "GET" || method === "PATCH";
  }

  if (
    path.length === 4 &&
    resource === "conversations" &&
    isC19ConversationId(path[2]) &&
    path[3] === "messages"
  ) {
    return method === "GET" || method === "POST";
  }

  if (
    method === "POST" &&
    path.length === 5 &&
    resource === "conversations" &&
    isC19ConversationId(path[2]) &&
    path[3] === "assets" &&
    path[4] === "upload-intents"
  ) {
    return true;
  }

  if (
    path.length === 5 &&
    resource === "conversations" &&
    isC19ConversationId(path[2]) &&
    path[3] === "assets" &&
    isC19AssetId(path[4])
  ) {
    return method === "GET";
  }

  if (
    method === "POST" &&
    path.length === 6 &&
    resource === "conversations" &&
    isC19ConversationId(path[2]) &&
    path[3] === "assets" &&
    isC19AssetId(path[4]) &&
    path[5] === "finalize"
  ) {
    return true;
  }

  if (
    method === "POST" &&
    path.length === 8 &&
    resource === "conversations" &&
    isC19ConversationId(path[2]) &&
    path[3] === "records" &&
    isC19RecordId(path[4]) &&
    path[5] === "assets" &&
    isC19AssetId(path[6]) &&
    path[7] === "access-intents"
  ) {
    return true;
  }

  if (
    path.length === 4 &&
    resource === "conversations" &&
    isC19ConversationId(path[2]) &&
    ["delivered", "read"].includes(path[3])
  ) {
    return method === "POST";
  }

  if (
    method === "GET" &&
    path.length === 4 &&
    resource === "conversations" &&
    isC19ConversationId(path[2]) &&
    ["resume", "unread"].includes(path[3])
  ) {
    return true;
  }

  if (
    path.length === 3 &&
    resource === "groups" &&
    isC19ConversationId(path[2])
  ) {
    return method === "PATCH" || method === "DELETE";
  }

  if (
    method === "POST" &&
    path.length === 4 &&
    resource === "groups" &&
    isC19ConversationId(path[2]) &&
    ["leave", "members", "transfer-owner"].includes(path[3])
  ) {
    return true;
  }

  return (
    method === "DELETE" &&
    path.length === 5 &&
    resource === "groups" &&
    isC19ConversationId(path[2]) &&
    path[3] === "members" &&
    isIntegerPathSegment(path[4])
  );
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

function isAllowedKeyHealthPath(method: string, path: string[]) {
  if (path[0] !== "key-health" || path.length !== 2) {
    return false;
  }
  if (path[1] === "summary" || path[1] === "runs") {
    return method === "GET";
  }
  return path[1] === "run" && method === "POST";
}

function isAllowedPPath(method: string, path: string[]) {
  if (path[0] !== "p") {
    return false;
  }
  // GET /p/products/{id}/upload-package  (取数)
  if (
    path.length === 4 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "upload-package"
  ) {
    return method === "GET";
  }
  // POST /p/products/{id}/dispatch  (派单)
  if (
    path.length === 4 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "dispatch"
  ) {
    return method === "POST";
  }
  // GET /p/uploads  (上架台账，P 系列驾驶舱)
  if (path.length === 2 && path[1] === "uploads") {
    return method === "GET";
  }
  // GET /p/products/board  (待上传/已上传分组)
  if (
    path.length === 3 &&
    path[1] === "products" &&
    path[2] === "board"
  ) {
    return method === "GET";
  }
  // POST /p/dispatch/batch  (批量上传，串行队列)
  if (
    path.length === 3 &&
    path[1] === "dispatch" &&
    path[2] === "batch"
  ) {
    return method === "POST";
  }
  return false;
}

function isAllowedFPath(method: string, path: string[]) {
  if (path[0] !== "f") {
    return false;
  }
  // 类目树逐层下钻 / 搜索（共享 K 的谷歌树 + F 标记层统计）
  if (
    path.length === 3 &&
    path[1] === "categories" &&
    ["tree", "search"].includes(path[2])
  ) {
    return method === "GET";
  }
  // 类目产品画像（谷歌类目 id 是短数字串，非 UUID）
  if (
    path.length === 4 &&
    path[1] === "categories" &&
    /^[A-Za-z0-9_-]{1,32}$/.test(path[2]) &&
    path[3] === "profile"
  ) {
    return method === "GET" || method === "POST";
  }
  // 市场参考页（图搜种子图的来源网页，组头展示竞品定价/变体）
  if (
    path.length === 4 &&
    path[1] === "categories" &&
    /^[A-Za-z0-9_-]{1,32}$/.test(path[2]) &&
    path[3] === "market-refs"
  ) {
    return method === "GET";
  }
  // 富化运行：发起 + 列表 + 单个进度
  if (path.length === 2 && path[1] === "runs") {
    return method === "GET" || method === "POST";
  }
  if (path.length === 3 && path[1] === "runs" && isUuidPathSegment(path[2])) {
    return method === "GET";
  }
  // 关键词列表 + 审核
  if (path.length === 2 && path[1] === "keywords") {
    return method === "GET";
  }
  if (
    path.length === 3 &&
    path[1] === "keywords" &&
    isUuidPathSegment(path[2])
  ) {
    return method === "PATCH";
  }
  // 候选池：列表 / 手动新增（过渡期贴 1688 链接）/ 审核 / 进 K
  if (path.length === 2 && path[1] === "candidates") {
    return method === "GET" || method === "POST";
  }
  if (
    path.length === 3 &&
    path[1] === "candidates" &&
    isUuidPathSegment(path[2])
  ) {
    return method === "PATCH";
  }
  if (
    path.length === 4 &&
    path[1] === "candidates" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "import-to-k"
  ) {
    return method === "POST";
  }
  // 候选图片代理（后端回源 alicdn + 磁盘缓存；thumb/full 由 query 定）
  if (
    path.length === 4 &&
    path[1] === "candidates" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "image"
  ) {
    return method === "GET";
  }
  // 额度视图（Serper / F 独立 1688 总闸）
  if (path.length === 2 && path[1] === "quota") {
    return method === "GET";
  }
  return false;
}

function isAllowedHPath(method: string, path: string[]) {
  if (path[0] !== "h") {
    return false;
  }
  if (path.length === 2 && path[1] === "runs") {
    return method === "GET";
  }
  if (
    path.length === 3 &&
    path[1] === "runs" &&
    path[2] === "trigger"
  ) {
    return method === "POST";
  }
  if (
    path.length === 3 &&
    path[1] === "runs" &&
    isUuidPathSegment(path[2])
  ) {
    return method === "GET";
  }
  if (path.length === 2 && path[1] === "findings") {
    return method === "GET";
  }
  if (
    path.length === 3 &&
    path[1] === "findings" &&
    isUuidPathSegment(path[2])
  ) {
    return method === "PATCH";
  }
  return false;
}

function isAllowedCsPath(method: string, path: string[]) {
  if (path[0] !== "cs") {
    return false;
  }
  if (path.length === 2 && path[1] === "messages") {
    return method === "GET";
  }
  if (
    path.length === 3 &&
    path[1] === "messages" &&
    isUuidPathSegment(path[2])
  ) {
    return method === "GET" || method === "PATCH";
  }
  if (path.length === 2 && path[1] === "summary") {
    return method === "GET";
  }
  return false;
}

function isAllowedWPath(method: string, path: string[]) {
  if (path[0] !== "w") {
    return false;
  }
  if (
    path.length === 3 &&
    path[1] === "shipping" &&
    path[2] === "classes"
  ) {
    return method === "GET" || method === "POST";
  }
  if (
    path.length === 4 &&
    path[1] === "shipping" &&
    path[2] === "classes" &&
    isUuidPathSegment(path[3])
  ) {
    return method === "PATCH" || method === "DELETE";
  }
  if (
    path.length === 5 &&
    path[1] === "shipping" &&
    path[2] === "classes" &&
    isUuidPathSegment(path[3]) &&
    path[4] === "sync"
  ) {
    return method === "POST";
  }
  if (path.length === 3 && path[1] === "shipping" && path[2] === "rules") {
    return method === "GET" || method === "POST";
  }
  if (
    path.length === 4 &&
    path[1] === "shipping" &&
    path[2] === "rules" &&
    isUuidPathSegment(path[3])
  ) {
    return method === "PATCH" || method === "DELETE";
  }
  if (
    path.length === 3 &&
    path[1] === "shipping" &&
    path[2] === "simulate"
  ) {
    return method === "POST";
  }
  if (
    path.length === 4 &&
    path[1] === "shipping" &&
    path[2] === "assign" &&
    isUuidPathSegment(path[3])
  ) {
    return method === "POST";
  }
  if (
    path.length === 3 &&
    path[1] === "shipping" &&
    path[2] === "assign-all"
  ) {
    return method === "POST";
  }
  if (path.length === 3 && path[1] === "shipping" && path[2] === "board") {
    return method === "GET";
  }
  if (
    path.length === 4 &&
    path[1] === "shipping" &&
    path[2] === "products" &&
    isUuidPathSegment(path[3])
  ) {
    return method === "PATCH";
  }
  if (path.length === 2 && path[1] === "orders") {
    return method === "GET";
  }
  if (
    path.length === 4 &&
    path[1] === "orders" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "tracking"
  ) {
    return method === "PATCH";
  }
  if (
    path.length === 4 &&
    path[1] === "orders" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "refresh-tracking"
  ) {
    return method === "POST";
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

  // 类目下拉搜索
  if (path.length === 3 && path[1] === "categories" && path[2] === "search") {
    return method === "GET";
  }

  // 叶子类目规格模板：树命名空间由受校验的 ?tree=google|amazon 传递。
  if (
    path.length === 4 &&
    path[1] === "categories" &&
    isIntegerPathSegment(path[2]) &&
    path[3] === "spec-template"
  ) {
    return method === "GET" || method === "PUT";
  }

  if (
    path.length === 5 &&
    path[1] === "categories" &&
    isIntegerPathSegment(path[2]) &&
    path[3] === "spec-template" &&
    path[4] === "draft"
  ) {
    return method === "POST";
  }

  // R→K 搬运
  if (path.length === 3 && path[1] === "products" && path[2] === "import-from-r") {
    return method === "POST";
  }

  // 临时作图参考图代理
  if (
    path.length === 4 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "reference-image"
  ) {
    return method === "GET";
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

  // 1688 文本只解析不落库；运营确认后仍走产品 PATCH 保存。
  if (
    path.length === 5 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "specs" &&
    path[4] === "parse-paste"
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
    ["generate-copy", "generate-image-brief", "brand-audit"].includes(path[3])
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

  // 一次性作图：批量渲染 + 进度 + 失败重试
  if (
    path.length === 4 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "render-images"
  ) {
    return method === "POST";
  }

  if (
    path.length === 4 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "render-jobs"
  ) {
    return method === "GET";
  }

  // 渲染资产（暂存/已保存）+ 保存 + 单张重做
  if (
    path.length === 4 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "render-assets"
  ) {
    return method === "GET";
  }

  if (
    path.length === 5 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "render-assets" &&
    path[4] === "save"
  ) {
    return method === "POST";
  }

  if (
    path.length === 4 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "render-rework"
  ) {
    return method === "POST";
  }

  if (
    path.length === 5 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "render-images" &&
    path[4] === "retry"
  ) {
    return method === "POST";
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

  // FAQ 人工编辑：page_faq 单一数据源，重推后可见 FAQ 与 schema 自动一致。
  if (
    path.length === 4 &&
    path[1] === "products" &&
    isUuidPathSegment(path[2]) &&
    path[3] === "faq"
  ) {
    return method === "PUT";
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

    if (
      method === "GET" &&
      path.length === 5 &&
      path[2] === "runs" &&
      (isUuidPathSegment(path[3]) || path[3] === "latest") &&
      ["status", "events"].includes(path[4])
    ) {
      return true;
    }

    if (
      method === "GET" &&
      path.length === 3 &&
      ["groups", "quota", "reports"].includes(path[2])
    ) {
      return true;
    }

    if (
      method === "POST" &&
      path.length === 5 &&
      path[2] === "reports" &&
      isUuidPathSegment(path[3]) &&
      ["approve", "reject", "opus-review", "expand"].includes(path[4])
    ) {
      return true;
    }

    if (
      method === "GET" &&
      path.length === 5 &&
      path[2] === "reports" &&
      isUuidPathSegment(path[3]) &&
      ["detail", "expansion"].includes(path[4])
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

function isAllowedArcadePath(method: string, path: string[]) {
  if (path[0] !== "arcade" || path[1] !== "high-scores") {
    return false;
  }

  if (method === "GET") {
    return path.length === 2;
  }

  return (
    method === "POST" &&
    path.length === 3 &&
    ALLOWED_ARCADE_GAME_IDS.has(path[2])
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
    isAllowedC19Path(method, path) ||
    isAllowedPermissionPath(method, path) ||
    isAllowedUsersPath(method, path) ||
    isAllowedKPath(method, path) ||
    isAllowedIPath(method, path) ||
    isAllowedFPath(method, path) ||
    isAllowedHPath(method, path) ||
    isAllowedCsPath(method, path) ||
    isAllowedWPath(method, path) ||
    isAllowedRPath(method, path) ||
    isAllowedRwPath(method, path) ||
    isAllowedArcadePath(method, path) ||
    isAllowedNotificationsPath(method, path) ||
    isAllowedPPath(method, path)
  ) {
    return withApiLayer("app", requestedPath);
  }

  if (
    (method === "GET" && ALLOWED_CONTROL_PLANE_LIST_PATHS.has(requestedPath)) ||
    isAllowedControlPlaneResourcePath(method, path) ||
    (method === "GET" && ALLOWED_MODULE_REGISTRY_PATHS.has(requestedPath)) ||
    isAllowedModuleControlPath(method, path) ||
    isAllowedApiKeyOrchestrationPath(method, path) ||
    isAllowedKeyHealthPath(method, path) ||
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
    // Webhook 登记簿（模块控制页 Webhook 标签，只记录不调用）
    (requestedPath === "webhook-registry" &&
      (method === "GET" || method === "POST")) ||
    (path.length === 2 &&
      path[0] === "webhook-registry" &&
      method === "DELETE")
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

const C19_JSON_BODY_MAX_BYTES = 16 * 1024;

class ProxyPayloadTooLargeError extends Error {}

function isC19MessageSend(method: string, path: string[]) {
  return (
    method === "POST" &&
    path.length === 4 &&
    path[0] === "c19" &&
    path[1] === "conversations" &&
    isC19ConversationId(path[2]) &&
    path[3] === "messages"
  );
}

function isC19AssetControlWrite(method: string, path: string[]) {
  if (method !== "POST" || path[0] !== "c19" || path[1] !== "conversations") {
    return false;
  }
  return (
    (path.length === 5 &&
      isC19ConversationId(path[2]) &&
      path[3] === "assets" &&
      path[4] === "upload-intents") ||
    (path.length === 6 &&
      isC19ConversationId(path[2]) &&
      path[3] === "assets" &&
      isC19AssetId(path[4]) &&
      path[5] === "finalize") ||
    (path.length === 8 &&
      isC19ConversationId(path[2]) &&
      path[3] === "records" &&
      isC19RecordId(path[4]) &&
      path[5] === "assets" &&
      isC19AssetId(path[6]) &&
      path[7] === "access-intents")
  );
}

function isC19MomentJsonWrite(method: string, path: string[]) {
  if (path[0] !== "c19" || path[1] !== "moments") return false;
  return method !== "GET" && isAllowedC19Path(method, path);
}

function isC19BoundedJsonWrite(method: string, path: string[]) {
  return (
    isC19MessageSend(method, path) ||
    isC19AssetControlWrite(method, path) ||
    isC19MomentJsonWrite(method, path)
  );
}

async function readBodyWithLimit(request: NextRequest, maximumBytes: number) {
  const declaredLength = request.headers.get("content-length");
  if (declaredLength !== null) {
    const parsedLength = Number(declaredLength);
    if (
      !Number.isSafeInteger(parsedLength) ||
      parsedLength < 0 ||
      parsedLength > maximumBytes
    ) {
      throw new ProxyPayloadTooLargeError();
    }
  }
  if (!request.body) return new Uint8Array();

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maximumBytes) {
        await reader.cancel();
        throw new ProxyPayloadTooLargeError();
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
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
    const isC19JsonWrite = isC19BoundedJsonWrite(request.method, path);

    if (
      isC19JsonWrite &&
      request.body !== null &&
      contentType?.split(";", 1)[0].trim().toLowerCase() !== "application/json"
    ) {
      return Response.json(
        { detail: "通讯控制请求必须使用 JSON；文件字节不能经过此前端代理。" },
        { status: 415 },
      );
    }

    applySessionHeaders(headers, request);
    applyTrustedClientIp(headers, request.headers);
    applyForceRefreshHeaders(headers, request);
    if (contentType) {
      headers.set("Content-Type", contentType);
    }
    if (idempotencyKey) {
      headers.set("Idempotency-Key", idempotencyKey);
    }

    const requestBody =
      request.method === "GET"
        ? undefined
        : isC19JsonWrite
          ? await readBodyWithLimit(request, C19_JSON_BODY_MAX_BYTES)
          : await request.arrayBuffer();
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
      "x-accel-buffering",
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
  } catch (error) {
    if (error instanceof ProxyPayloadTooLargeError) {
      return Response.json(
        { detail: "通讯 JSON 控制请求体过大。" },
        { status: 413 },
      );
    }
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

export function PUT(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}

export function DELETE(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}
