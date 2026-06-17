export type LiveExecutionMode = "mock" | "staging" | "live";

export type ReadinessCheckStatus = "pass" | "fail" | "warn";

export type LivePolicyScope = "global" | "org" | "module";

export type LivePolicyStatus = "active" | "disabled";

export type LiveGateStatus =
  | "allowed"
  | "blocked"
  | "staging_only"
  | "backend_unavailable";

export type CanaryState =
  | "live"
  | "staging"
  | "mock"
  | "not_configured"
  | "backend_unavailable";

export type ReadinessCheckResult = {
  check: string;
  status: ReadinessCheckStatus;
  reason: string;
  metadata: Record<string, unknown>;
};

export type PreLiveValidationReport = {
  engine: "PreLiveValidationEngine";
  passed: boolean;
  generated_at: string | null;
  checks: ReadinessCheckResult[];
};

export type ProductionReadinessReport = {
  engine: "ProductionReadinessEngine";
  ready: boolean;
  generated_at: string | null;
  checks: ReadinessCheckResult[];
};

export type LiveGatePolicyRead = {
  policy_id: string;
  org_id: string;
  policy_scope: LivePolicyScope;
  scope_key: string;
  enabled: boolean;
  staging_only: boolean;
  rollout_percentage: number;
  allowed_orgs: string[];
  allowed_modules: string[];
  status: LivePolicyStatus;
  created_at: string | null;
  updated_at: string | null;
  metadata: Record<string, unknown>;
};

export type LiveGateRuntimeState = {
  live_gate_status: LiveGateStatus;
  canary_state: CanaryState;
  execution_mode: LiveExecutionMode;
  blocked_reason: string;
  readiness_passed: boolean;
  production_ready: boolean;
  active_policy_count: number;
  rollout_percentage: number;
  source: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function booleanValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function numberValue(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : fallback;
}

function stringArray(value: unknown) {
  return Array.isArray(value)
    ? value.filter((entry): entry is string => typeof entry === "string")
    : [];
}

function normalizeCheckStatus(value: unknown): ReadinessCheckStatus {
  return value === "pass" || value === "fail" || value === "warn"
    ? value
    : "fail";
}

function normalizePolicyScope(value: unknown): LivePolicyScope {
  return value === "global" || value === "org" || value === "module"
    ? value
    : "module";
}

function normalizePolicyStatus(value: unknown): LivePolicyStatus {
  return value === "active" || value === "disabled" ? value : "disabled";
}

function normalizeMetadata(value: unknown) {
  return isRecord(value) ? value : {};
}

export function normalizeReadinessCheckResult(
  value: unknown,
): ReadinessCheckResult | null {
  if (!isRecord(value)) {
    return null;
  }

  const check = stringValue(value.check);
  if (!check) {
    return null;
  }

  return {
    check,
    metadata: normalizeMetadata(value.metadata),
    reason: stringValue(value.reason, "Readiness check did not include a reason."),
    status: normalizeCheckStatus(value.status),
  };
}

export function normalizePreLiveValidationReport(
  value: unknown,
): PreLiveValidationReport {
  const record = isRecord(value) ? value : {};
  const checks = Array.isArray(record.checks)
    ? record.checks
        .map(normalizeReadinessCheckResult)
        .filter((item): item is ReadinessCheckResult => item !== null)
    : [];

  return {
    checks,
    engine: "PreLiveValidationEngine",
    generated_at: optionalString(record.generated_at),
    passed: booleanValue(record.passed, false),
  };
}

export function normalizeProductionReadinessReport(
  value: unknown,
): ProductionReadinessReport {
  const record = isRecord(value) ? value : {};
  const checks = Array.isArray(record.checks)
    ? record.checks
        .map(normalizeReadinessCheckResult)
        .filter((item): item is ReadinessCheckResult => item !== null)
    : [];

  return {
    checks,
    engine: "ProductionReadinessEngine",
    generated_at: optionalString(record.generated_at),
    ready: booleanValue(record.ready, false),
  };
}

export function normalizeLiveGatePolicyRead(
  value: unknown,
): LiveGatePolicyRead | null {
  if (!isRecord(value)) {
    return null;
  }

  const policyId = stringValue(value.policy_id);
  const scopeKey = stringValue(value.scope_key);
  if (!policyId || !scopeKey) {
    return null;
  }

  return {
    allowed_modules: stringArray(value.allowed_modules),
    allowed_orgs: stringArray(value.allowed_orgs),
    created_at: optionalString(value.created_at),
    enabled: booleanValue(value.enabled, false),
    metadata: normalizeMetadata(value.metadata),
    org_id: stringValue(value.org_id),
    policy_id: policyId,
    policy_scope: normalizePolicyScope(value.policy_scope),
    rollout_percentage: Math.min(
      100,
      Math.max(0, numberValue(value.rollout_percentage, 0)),
    ),
    scope_key: scopeKey,
    staging_only: booleanValue(value.staging_only, true),
    status: normalizePolicyStatus(value.status),
    updated_at: optionalString(value.updated_at),
  };
}

export function normalizeLiveGatePolicies(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map(normalizeLiveGatePolicyRead)
    .filter((item): item is LiveGatePolicyRead => item !== null);
}

function firstFailedCheck(
  report: Pick<PreLiveValidationReport | ProductionReadinessReport, "checks">,
) {
  return report.checks.find((check) => check.status === "fail") ?? null;
}

export function deriveLiveGateRuntimeState({
  policies,
  policyError,
  productionReadiness,
  productionReadinessError,
  readiness,
  readinessError,
}: {
  readiness: PreLiveValidationReport | null;
  productionReadiness: ProductionReadinessReport | null;
  policies: readonly LiveGatePolicyRead[];
  readinessError?: string;
  productionReadinessError?: string;
  policyError?: string;
}): LiveGateRuntimeState {
  const errors = [
    readinessError,
    productionReadinessError,
    policyError,
  ].filter(Boolean);
  const backendUnavailable = errors.length > 0 && !readiness && !productionReadiness;
  const activePolicies = policies.filter((policy) => policy.status === "active");
  const enabledPolicies = activePolicies.filter((policy) => policy.enabled);
  const livePolicies = enabledPolicies.filter((policy) => !policy.staging_only);
  const rolloutPercentage = livePolicies.reduce(
    (max, policy) => Math.max(max, policy.rollout_percentage),
    0,
  );
  const readinessPassed = readiness?.passed === true;
  const productionReady = productionReadiness?.ready === true;
  const readinessFailure = readiness ? firstFailedCheck(readiness) : null;
  const productionFailure = productionReadiness
    ? firstFailedCheck(productionReadiness)
    : null;
  const liveEligible =
    readinessPassed &&
    productionReady &&
    livePolicies.length > 0 &&
    rolloutPercentage > 0;
  const stagingEligible =
    readinessPassed &&
    enabledPolicies.some((policy) => policy.staging_only || policy.enabled);

  if (backendUnavailable) {
    return {
      active_policy_count: activePolicies.length,
      blocked_reason: errors[0] ?? "PRE20-Q live gate state is unavailable.",
      canary_state: "backend_unavailable",
      execution_mode: "mock",
      live_gate_status: "backend_unavailable",
      production_ready: false,
      readiness_passed: false,
      rollout_percentage: rolloutPercentage,
      source:
        "/live-gate/readiness + /live-gate/production-readiness + /live-gate/policies",
    };
  }

  if (liveEligible) {
    return {
      active_policy_count: activePolicies.length,
      blocked_reason: "Live gate, production readiness, and rollout policy allow live exposure.",
      canary_state: rolloutPercentage >= 100 ? "live" : "staging",
      execution_mode: "live",
      live_gate_status: "allowed",
      production_ready: true,
      readiness_passed: true,
      rollout_percentage: rolloutPercentage,
      source:
        "/live-gate/readiness + /live-gate/production-readiness + /live-gate/policies",
    };
  }

  if (stagingEligible) {
    return {
      active_policy_count: activePolicies.length,
      blocked_reason:
        productionFailure?.reason ||
        policyError ||
        "Live gate is staging-only until production readiness and rollout policy pass.",
      canary_state: "staging",
      execution_mode: "staging",
      live_gate_status: "staging_only",
      production_ready: productionReady,
      readiness_passed: readinessPassed,
      rollout_percentage: rolloutPercentage,
      source:
        "/live-gate/readiness + /live-gate/production-readiness + /live-gate/policies",
    };
  }

  return {
    active_policy_count: activePolicies.length,
    blocked_reason:
      readinessFailure?.reason ||
      productionFailure?.reason ||
      readinessError ||
      productionReadinessError ||
      policyError ||
      "PRE20-Q live gate is blocked until readiness, production checks, and rollout policy pass.",
    canary_state: activePolicies.length > 0 ? "mock" : "not_configured",
    execution_mode: "mock",
    live_gate_status: "blocked",
    production_ready: productionReady,
    readiness_passed: readinessPassed,
    rollout_percentage: rolloutPercentage,
    source:
      "/live-gate/readiness + /live-gate/production-readiness + /live-gate/policies",
  };
}
