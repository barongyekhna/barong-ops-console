import {
  Archive,
  Bot,
  Boxes,
  CircleAlert,
  ClipboardCheck,
  Database,
  LayoutDashboard,
  LockKeyhole,
  Package,
  Settings,
  Sparkles,
  UserRoundCog,
  Workflow,
  type LucideIcon,
} from "lucide-react";

import type {
  ExecutionProviderAccessState,
  ExecutionProviderContract,
} from "@/lib/execution-provider";
import type {
  CanaryState,
  LiveExecutionMode,
  LiveGateRuntimeState,
  LiveGateStatus,
} from "@/lib/live-gate";
import type {
  ModuleAdapterAccessState,
  ModuleAdapterContract,
} from "@/lib/module-adapter";
import {
  findModuleAccessState,
  getNavigationStateForModule,
  type ModuleAccessState,
  type ModuleAwareNavigationRecord,
  type ModuleManifest,
  type ModuleNavigationState,
  type ModuleStatus,
} from "@/lib/module-registry";
import { navigationItems, navigationModuleRecords } from "@/lib/navigation";
import type { FrontendPermissions } from "@/lib/permissions";

export type ProductCapabilityStateName =
  | "allowed"
  | "forbidden"
  | "hidden"
  | "partial"
  | "mock"
  | "adapter_pending"
  | "no_execution"
  | "backend_unavailable";

export type SidebarCapabilityState =
  | "allowed"
  | "forbidden"
  | "hidden"
  | "partial";

export type ProductCapabilityBadge =
  | "locked"
  | "read_only"
  | "mock"
  | "adapter_pending"
  | "no_execution"
  | "backend_unavailable"
  | null;

export type ProductCapabilityApiBinding = {
  route_namespace: string;
  api_namespace: string;
  no_api: boolean;
  route_bound: boolean;
  api_bound: boolean;
  adapter_bindings: string[];
};

export type ProductCapabilityItem = {
  href: string;
  icon: LucideIcon;
  label: string;
  description: string;
  module_key: string;
  nav_group: string;
  nav_order: number;
  route_namespace: string;
  state: ProductCapabilityStateName;
  sidebar_state: SidebarCapabilityState;
  badge: ProductCapabilityBadge;
  reason: string;
  unlock_condition: string;
  required_permission: string;
  required_org_state: string;
  required_module_state: string;
  required_execution_mode: string;
  module_status: ModuleStatus | "unknown";
  permission_state: ModuleNavigationState["accessState"];
  org_visibility: "visible" | "hidden" | "unknown" | "unavailable";
  adapter_state: string;
  provider_state: string;
  execution_mode: LiveExecutionMode;
  live_gate_status: LiveGateStatus;
  canary_state: CanaryState;
  approval_state: FrontendExecutionState["approval_state"];
  blocked_reason: string;
  route_bound: boolean;
  can_enter: boolean;
  api_binding: ProductCapabilityApiBinding;
};

export type ProductCapabilityGroup = {
  label: string;
  items: ProductCapabilityItem[];
};

export type FrontendPermissionSnapshot = {
  source: "/auth/me";
  is_owner_full_access: boolean;
  permission_count: number;
  permissions: string[];
};

export type FrontendOrgContext = {
  source: "/modules/me";
  state: "active" | "unknown" | "backend_unavailable";
  role: string;
  visible_modules: number;
  hidden_modules: number;
  reason: string;
};

export type FrontendExecutionState = {
  source: string;
  live_gate_status: LiveGateStatus;
  canary_state: CanaryState;
  approval_state:
    | "not_required"
    | "required"
    | "waiting_c12"
    | "blocked"
    | "unknown";
  execution_mode: LiveExecutionMode;
  blocked_reason: string;
  adapter_count: number;
  adapter_pending_count: number;
  provider_count: number;
  no_execution_count: number;
  readiness_passed: boolean;
  production_ready: boolean;
  rollout_percentage: number;
};

export type FrontendCapabilityGraph = {
  items: ProductCapabilityItem[];
  sidebarItems: ProductCapabilityItem[];
  groups: ProductCapabilityGroup[];
  byModuleKey: Map<string, ProductCapabilityItem>;
  permissionSnapshot: FrontendPermissionSnapshot;
  orgContext: FrontendOrgContext;
  executionState: FrontendExecutionState;
};

const ICONS: Record<string, LucideIcon> = {
  Archive,
  Bot,
  Boxes,
  CircleAlert,
  ClipboardCheck,
  Database,
  LayoutDashboard,
  LockKeyhole,
  Package,
  Settings,
  Sparkles,
  UserRoundCog,
  Workflow,
};

const GROUP_ORDER = new Map([
  ["Core System", 10],
  ["Overview", 10],
  ["Operations", 20],
  ["Governance", 30],
  ["Registry", 40],
  ["System", 50],
]);

const INTERNAL_EXERCISE_MODULE_KEY = [
  "experimental",
  ["foun", "dation_", "de", "mo"].join(""),
].join(".");

export const PRODUCT_HIDDEN_MODULE_KEYS = new Set([
  "admin.settings",
  "business.products",
  INTERNAL_EXERCISE_MODULE_KEY,
  "integration.n8n_test_bridge",
  "system.memory_events",
]);

const routeByModuleKey = new Map(
  navigationModuleRecords.map((record) => [record.module_key, record]),
);

function isOwnerFullAccess(
  permissions: { is_owner_full_access?: boolean } | null | undefined,
) {
  return permissions?.is_owner_full_access === true;
}

function missingPermissionText(
  record: ModuleAwareNavigationRecord,
  accessState: ModuleAccessState | null,
) {
  const missing = accessState?.missing_permissions ?? [];
  if (missing.length > 0) {
    return missing.join(", ");
  }
  if (record.required_permission) {
    return record.required_permission;
  }
  return "No additional permission required.";
}

function groupOrder(label: string) {
  return GROUP_ORDER.get(label) ?? 999;
}

function routeIcon(record: ModuleAwareNavigationRecord, manifest: ModuleManifest | null) {
  return record.icon ?? ICONS[manifest?.navigation.icon ?? ""] ?? Boxes;
}

function routeLabel(record: ModuleAwareNavigationRecord, manifest: ModuleManifest | null) {
  return manifest?.navigation.label || manifest?.display_name || record.label;
}

function routeGroup(record: ModuleAwareNavigationRecord, manifest: ModuleManifest | null) {
  if (manifest?.navigation.group) {
    if (manifest.navigation.group === "Overview") {
      return "Core System";
    }
    if (manifest.module_key === "system.operation_logs") {
      return "Operations";
    }
    return manifest.navigation.group;
  }
  return record.category === "core" ? "Core System" : "Operations";
}

function routeOrder(record: ModuleAwareNavigationRecord, manifest: ModuleManifest | null) {
  if (manifest?.module_key === "system.operation_logs") {
    return 5;
  }
  if (manifest) {
    return manifest.navigation.order;
  }
  const navigationItem = navigationItems.find(
    (item) => item.module_key === record.module_key,
  );
  return navigationItem?.status === "sealed" ? 10 : 50;
}

function recordFromManifest(manifest: ModuleManifest): ModuleAwareNavigationRecord {
  return {
    category: manifest.category,
    denied_behavior: manifest.denied_behavior,
    href: manifest.route_namespace,
    icon: ICONS[manifest.navigation.icon] ?? Boxes,
    label: manifest.navigation.label || manifest.display_name,
    module_key: manifest.module_key,
    owner_only: manifest.navigation.owner_only,
    required_permission: manifest.required_permissions[0],
    route_namespace: manifest.route_namespace,
    status: manifest.status,
  };
}

function adapterForModule(
  moduleKey: string,
  adapters: readonly ModuleAdapterAccessState[],
) {
  return adapters.find((adapter) => adapter.module_key === moduleKey) ?? null;
}

function adapterContractForModule(
  moduleKey: string,
  adapters: readonly ModuleAdapterContract[],
) {
  return adapters.find((adapter) => adapter.module_key === moduleKey) ?? null;
}

function providersForModule(
  moduleKey: string,
  providers: readonly ExecutionProviderAccessState[],
) {
  return providers.filter((provider) => provider.module_key === moduleKey);
}

function providerContractsForModule(
  moduleKey: string,
  providers: readonly ExecutionProviderContract[],
) {
  return providers.filter((provider) => provider.module_key === moduleKey);
}

function hasMockProvider(
  accessItems: readonly ExecutionProviderAccessState[],
  contracts: readonly ExecutionProviderContract[],
) {
  return (
    accessItems.some((provider) => provider.execution_mode === "mock") ||
    contracts.some((provider) =>
      provider.supported_execution_modes.includes("mock"),
    )
  );
}

function hasUnavailableProvider(accessItems: readonly ExecutionProviderAccessState[]) {
  return accessItems.some(
    (provider) =>
      provider.unavailable ||
      provider.blocked ||
      provider.provider_access_state === "provider_pending" ||
      provider.provider_access_state === "unavailable" ||
      provider.provider_access_state === "blocked" ||
      provider.provider_access_state === "disabled" ||
      provider.provider_status === "provider_pending" ||
      provider.provider_status === "provider_unavailable" ||
      provider.provider_status === "disabled",
  );
}

function requiresExecutionSurface({
  adapter,
  manifest,
  providerAccess,
  providerContracts,
}: {
  manifest: ModuleManifest | null;
  adapter: ModuleAdapterAccessState | null;
  providerAccess: readonly ExecutionProviderAccessState[];
  providerContracts: readonly ExecutionProviderContract[];
}) {
  return Boolean(
    manifest?.execution_provider_required ||
      adapter?.requires_execution_provider ||
      providerAccess.length > 0 ||
      providerContracts.length > 0,
  );
}

function stateFromSources({
  adapter,
  adapterAccessUnknown,
  executionProviderAccessUnknown,
  executionState,
  manifest,
  moduleAccessState,
  navigationState,
  providerAccess,
  providerContracts,
  record,
  registryUnavailable,
  routeBound,
}: {
  adapter: ModuleAdapterAccessState | null;
  adapterAccessUnknown: boolean;
  executionProviderAccessUnknown: boolean;
  executionState: FrontendExecutionState;
  manifest: ModuleManifest | null;
  moduleAccessState: ModuleAccessState | null;
  navigationState: ModuleNavigationState;
  providerAccess: readonly ExecutionProviderAccessState[];
  providerContracts: readonly ExecutionProviderContract[];
  record: ModuleAwareNavigationRecord;
  registryUnavailable: boolean;
  routeBound: boolean;
}) {
  const requiredPermission = missingPermissionText(record, moduleAccessState);
  const executionRequired = requiresExecutionSurface({
    adapter,
    manifest,
    providerAccess,
    providerContracts,
  });
  const base = {
    reason: "Capability is visible, permission-allowed, and backed by a registered route.",
    required_execution_mode: executionRequired
      ? "PRE20-Q execution gate and provider readiness must allow a non-blocked mode."
      : "Read-only backend capability.",
    required_module_state: manifest?.status ?? record.status ?? "enabled",
    required_org_state: "Active organization context with module visibility.",
    required_permission: requiredPermission,
    state: "allowed" as ProductCapabilityStateName,
    unlock_condition: "Capability is available for this account and organization.",
  };

  if (PRODUCT_HIDDEN_MODULE_KEYS.has(record.module_key)) {
    return {
      ...base,
      reason: "This route is excluded from production product navigation.",
      state: "hidden" as const,
      unlock_condition:
        "Install a durable product capability with a non-placeholder backend binding.",
    };
  }

  if (navigationState.isHidden) {
    return {
      ...base,
      reason:
        navigationState.reason ||
        "C18 module visibility or C05 permission snapshot hides this capability.",
      state: "hidden" as const,
      unlock_condition: "Grant module visibility and the required permission.",
    };
  }

  if (navigationState.isLocked) {
    return {
      ...base,
      reason:
        navigationState.reason ||
        "C05 permission snapshot forbids this capability for the current account.",
      state: "forbidden" as const,
      unlock_condition: "Grant the missing permission in C05/C06.",
    };
  }

  if (!routeBound) {
    return {
      ...base,
      reason: "Module is registered, but no frontend product route is bound.",
      state: "partial" as const,
      unlock_condition: "Bind a durable frontend route before exposing this capability.",
    };
  }

  if (registryUnavailable && !manifest) {
    return {
      ...base,
      reason: "Module registry is unavailable; frontend is using route metadata only.",
      state: "partial" as const,
      unlock_condition: "Restore /modules/registry and /modules/me.",
    };
  }

  if (navigationState.moduleAccessUnknown) {
    return {
      ...base,
      reason:
        navigationState.reason ||
        "C18 module visibility is unavailable; frontend is using a safe partial state.",
      state: "partial" as const,
      unlock_condition: "Restore /modules/me.",
    };
  }

  if (
    navigationState.accessState === "adapter_pending" ||
    manifest?.status === "adapter_pending" ||
    adapter?.adapter_access_state === "adapter_pending"
  ) {
    return {
      ...base,
      reason:
        adapter?.reason ||
        navigationState.reason ||
        "Adapter readiness is pending.",
      required_execution_mode: "Adapter contract must be ready before execution.",
      state: "adapter_pending" as const,
      unlock_condition: "Complete adapter readiness and provider binding.",
    };
  }

  if (adapter?.hidden) {
    return {
      ...base,
      reason: adapter.reason || "Adapter access state hides this capability.",
      state: "hidden" as const,
      unlock_condition: "Expose the adapter for this account and organization.",
    };
  }

  if (adapter?.locked) {
    return {
      ...base,
      reason: adapter.reason || "Adapter access state is locked.",
      state: "forbidden" as const,
      unlock_condition: "Grant adapter action permissions.",
    };
  }

  if (
    navigationState.isUnavailable ||
    adapter?.unavailable ||
    manifest?.status === "planned" ||
    manifest?.status === "disabled" ||
    manifest?.status === "unavailable" ||
    manifest?.status === "deprecated"
  ) {
    return {
      ...base,
      reason:
        adapter?.reason ||
        navigationState.reason ||
        "Capability exists but is not fully available.",
      required_execution_mode: "Read-only route may be visible, but actions remain disabled.",
      state: "partial" as const,
      unlock_condition: "Enable the module and adapter readiness chain.",
    };
  }

  if (executionRequired && executionState.live_gate_status === "backend_unavailable") {
    return {
      ...base,
      reason: executionState.blocked_reason,
      required_execution_mode: "PRE20-Q live gate state must be readable.",
      state: "backend_unavailable" as const,
      unlock_condition: "Restore PRE20-Q live gate status APIs.",
    };
  }

  if (
    executionRequired &&
    (executionState.live_gate_status === "blocked" ||
      hasUnavailableProvider(providerAccess) ||
      (manifest?.execution_provider_required &&
        providerAccess.length === 0 &&
        providerContracts.length === 0 &&
        !executionProviderAccessUnknown))
  ) {
    return {
      ...base,
      reason:
        providerAccess.find((provider) => provider.block_reason)?.block_reason ||
        executionState.blocked_reason ||
        "Execution is blocked by provider or PRE20-Q gate state.",
      required_execution_mode: "Execution provider and PRE20-Q gate must allow staging or live.",
      state: "no_execution" as const,
      unlock_condition: "Connect provider readiness and unblock PRE20-Q.",
    };
  }

  if (
    executionRequired &&
    (executionProviderAccessUnknown || hasMockProvider(providerAccess, providerContracts))
  ) {
    return {
      ...base,
      reason: executionProviderAccessUnknown
        ? "Execution provider state is unavailable; actions are fail-closed."
        : "Execution provider mode is mock or contract-only; no live execution is exposed.",
      required_execution_mode: "Live or approved non-mock provider mode.",
      state: executionProviderAccessUnknown ? "partial" as const : "mock" as const,
      unlock_condition: "Connect a permitted execution provider before enabling actions.",
    };
  }

  if (adapterAccessUnknown && manifest?.module_adapter_required) {
    return {
      ...base,
      reason: "Adapter access state is unavailable; actions are fail-closed.",
      required_execution_mode: "Adapter readiness must be confirmed.",
      state: "backend_unavailable" as const,
      unlock_condition: "Restore /module-adapters/me.",
    };
  }

  return base;
}

function badgeForState(state: ProductCapabilityStateName): ProductCapabilityBadge {
  if (state === "forbidden") {
    return "locked";
  }
  if (state === "adapter_pending") {
    return "adapter_pending";
  }
  if (state === "mock") {
    return "mock";
  }
  if (state === "no_execution") {
    return "no_execution";
  }
  if (state === "backend_unavailable") {
    return "backend_unavailable";
  }
  if (state === "partial") {
    return "read_only";
  }
  return null;
}

function sidebarStateForState(
  state: ProductCapabilityStateName,
): SidebarCapabilityState {
  if (state === "allowed" || state === "forbidden" || state === "hidden") {
    return state;
  }
  return "partial";
}

function orgVisibilityForNavigationState(state: ModuleNavigationState) {
  if (state.moduleAccessUnknown) {
    return "unknown" as const;
  }
  if (state.isHidden) {
    return "hidden" as const;
  }
  if (state.isVisible) {
    return "visible" as const;
  }
  return "unavailable" as const;
}

function adapterState(
  adapter: ModuleAdapterAccessState | null,
  contract: ModuleAdapterContract | null,
) {
  return (
    adapter?.adapter_access_state ??
    adapter?.adapter_status ??
    contract?.adapter_status ??
    "not_declared"
  );
}

function providerState(providerAccess: readonly ExecutionProviderAccessState[]) {
  if (providerAccess.length === 0) {
    return "not_declared";
  }
  return providerAccess
    .map((provider) => provider.provider_access_state || provider.provider_status)
    .join(", ");
}

function apiBindingForModule({
  adapter,
  manifest,
  record,
  routeBound,
}: {
  adapter: ModuleAdapterContract | null;
  manifest: ModuleManifest | null;
  record: ModuleAwareNavigationRecord;
  routeBound: boolean;
}): ProductCapabilityApiBinding {
  const adapterBindings = adapter
    ? adapter.api_bindings
        .map((binding) => binding.api_namespace ?? binding.route ?? binding.key)
        .filter(Boolean)
    : [];
  const apiNamespace = manifest?.api_namespace ?? "no_api";
  const noApi = manifest?.no_api ?? apiNamespace === "no_api";

  return {
    adapter_bindings: adapterBindings,
    api_bound: !noApi || adapterBindings.length > 0,
    api_namespace: apiNamespace,
    no_api: noApi,
    route_bound: routeBound,
    route_namespace: manifest?.route_namespace ?? record.route_namespace,
  };
}

function canEnterCapability({
  executionRequired,
  navigationState,
  routeBound,
  state,
}: {
  executionRequired: boolean;
  navigationState: ModuleNavigationState;
  routeBound: boolean;
  state: ProductCapabilityStateName;
}) {
  if (!routeBound || !navigationState.canEnter) {
    return false;
  }
  if (state === "hidden" || state === "forbidden") {
    return false;
  }
  if (
    executionRequired &&
    (state === "adapter_pending" ||
      state === "backend_unavailable" ||
      state === "no_execution")
  ) {
    return false;
  }
  return true;
}

export function deriveFrontendExecutionState({
  adapterAccessItems,
  executionProviderAccessItems,
  liveGate,
}: {
  adapterAccessItems: readonly ModuleAdapterAccessState[];
  executionProviderAccessItems: readonly ExecutionProviderAccessState[];
  liveGate: LiveGateRuntimeState;
}): FrontendExecutionState {
  const waitingApproval = executionProviderAccessItems.some(
    (provider) =>
      provider.approval_status === "waiting_c12" ||
      provider.approval_status === "blocked_approval_required",
  );
  const blockedApproval = executionProviderAccessItems.some(
    (provider) =>
      provider.requires_approval &&
      (provider.blocked || provider.no_execute_reason.includes("approval")),
  );
  const approvalRequired = executionProviderAccessItems.some(
    (provider) => provider.requires_approval,
  );
  const noExecutionProviders = executionProviderAccessItems.filter(
    (provider) => !provider.can_request_execution || !provider.executable,
  );
  const blockedProvider = executionProviderAccessItems.find(
    (provider) =>
      provider.block_reason || provider.no_execute_reason || provider.safe_status_message,
  );

  return {
    adapter_count: adapterAccessItems.length,
    adapter_pending_count: adapterAccessItems.filter(
      (adapter) => adapter.adapter_access_state === "adapter_pending",
    ).length,
    approval_state: waitingApproval
      ? "waiting_c12"
      : blockedApproval
        ? "blocked"
        : approvalRequired
          ? "required"
          : executionProviderAccessItems.length === 0
            ? "unknown"
            : "not_required",
    blocked_reason:
      liveGate.live_gate_status === "allowed"
        ? blockedProvider?.block_reason ||
          blockedProvider?.no_execute_reason ||
          liveGate.blocked_reason
        : liveGate.blocked_reason,
    canary_state: liveGate.canary_state,
    execution_mode: liveGate.execution_mode,
    live_gate_status: liveGate.live_gate_status,
    no_execution_count: noExecutionProviders.length,
    production_ready: liveGate.production_ready,
    provider_count: executionProviderAccessItems.length,
    readiness_passed: liveGate.readiness_passed,
    rollout_percentage: liveGate.rollout_percentage,
    source: liveGate.source,
  };
}

function permissionSnapshot(
  permissions: FrontendPermissions | null | undefined,
): FrontendPermissionSnapshot {
  return {
    is_owner_full_access: isOwnerFullAccess(permissions),
    permission_count: permissions?.permission_keys.length ?? 0,
    permissions: permissions?.permission_keys ?? [],
    source: "/auth/me",
  };
}

function orgContext({
  moduleAccessItems,
  moduleAccessUnknown,
  role,
}: {
  moduleAccessItems: readonly ModuleAccessState[];
  moduleAccessUnknown: boolean;
  role: string;
}): FrontendOrgContext {
  if (moduleAccessUnknown) {
    return {
      hidden_modules: moduleAccessItems.filter((item) => item.hidden).length,
      reason: "C18 module visibility is unavailable or incomplete.",
      role,
      source: "/modules/me",
      state: "unknown",
      visible_modules: moduleAccessItems.filter((item) => item.visible).length,
    };
  }

  return {
    hidden_modules: moduleAccessItems.filter((item) => item.hidden).length,
    reason: "C18 module visibility snapshot is available.",
    role,
    source: "/modules/me",
    state: "active",
    visible_modules: moduleAccessItems.filter((item) => item.visible).length,
  };
}

export function buildFrontendCapabilityGraph({
  adapterAccessItems,
  adapterAccessUnknown,
  adapterContracts,
  executionProviderAccessItems,
  executionProviderAccessUnknown,
  executionProviderContracts,
  liveGate,
  moduleAccessItems,
  moduleAccessUnknown,
  permissions,
  registryItems,
  registryUnavailable,
  role,
}: {
  permissions: FrontendPermissions | null | undefined;
  role: string;
  registryItems: readonly ModuleManifest[];
  registryUnavailable: boolean;
  moduleAccessItems: readonly ModuleAccessState[];
  moduleAccessUnknown: boolean;
  adapterContracts: readonly ModuleAdapterContract[];
  adapterAccessItems: readonly ModuleAdapterAccessState[];
  adapterAccessUnknown: boolean;
  executionProviderContracts: readonly ExecutionProviderContract[];
  executionProviderAccessItems: readonly ExecutionProviderAccessState[];
  executionProviderAccessUnknown: boolean;
  liveGate: LiveGateRuntimeState;
}): FrontendCapabilityGraph {
  const registryByModule = new Map(
    registryItems.map((manifest) => [manifest.module_key, manifest]),
  );
  const executionState = deriveFrontendExecutionState({
    adapterAccessItems,
    executionProviderAccessItems,
    liveGate,
  });
  const sources =
    registryItems.length > 0
      ? registryItems.map((manifest) => ({
          manifest,
          moduleKey: manifest.module_key,
          record: routeByModuleKey.get(manifest.module_key) ?? recordFromManifest(manifest),
        }))
      : navigationModuleRecords.map((record) => ({
          manifest: registryByModule.get(record.module_key) ?? null,
          moduleKey: record.module_key,
          record,
        }));
  const owner = isOwnerFullAccess(permissions);

  const items = sources
    .map(({ manifest, moduleKey, record }) => {
      const routeRecord = routeByModuleKey.get(moduleKey);
      const routeBound = Boolean(routeRecord);
      const moduleAccessState = findModuleAccessState(moduleKey, moduleAccessItems);
      const navigationState = getNavigationStateForModule(
        permissions,
        record,
        moduleAccessItems,
        { moduleAccessUnknown: moduleAccessUnknown || !moduleAccessState },
      );
      const adapterAccess = adapterForModule(moduleKey, adapterAccessItems);
      const adapterContract = adapterContractForModule(moduleKey, adapterContracts);
      const providerAccess = providersForModule(
        moduleKey,
        executionProviderAccessItems,
      );
      const providerContracts = providerContractsForModule(
        moduleKey,
        executionProviderContracts,
      );
      const sourceState = stateFromSources({
        adapter: adapterAccess,
        adapterAccessUnknown,
        executionProviderAccessUnknown,
        executionState,
        manifest,
        moduleAccessState,
        navigationState,
        providerAccess,
        providerContracts,
        record,
        registryUnavailable,
        routeBound,
      });
      const executionRequired = requiresExecutionSurface({
        adapter: adapterAccess,
        manifest,
        providerAccess,
        providerContracts,
      });
      const state = sourceState.state;
      const item: ProductCapabilityItem = {
        adapter_state: adapterState(adapterAccess, adapterContract),
        api_binding: apiBindingForModule({
          adapter: adapterContract,
          manifest,
          record,
          routeBound,
        }),
        approval_state: executionState.approval_state,
        badge: badgeForState(state),
        blocked_reason: sourceState.reason,
        can_enter: canEnterCapability({
          executionRequired,
          navigationState,
          routeBound,
          state,
        }),
        canary_state: executionState.canary_state,
        description: manifest?.description ?? "",
        execution_mode: executionState.execution_mode,
        href: routeRecord?.href ?? record.href,
        icon: routeIcon(record, manifest),
        label: routeLabel(record, manifest),
        live_gate_status: executionState.live_gate_status,
        module_key: moduleKey,
        module_status: manifest?.status ?? record.status ?? "unknown",
        nav_group: routeGroup(record, manifest),
        nav_order: routeOrder(record, manifest),
        org_visibility: orgVisibilityForNavigationState(navigationState),
        permission_state: navigationState.accessState,
        provider_state: providerState(providerAccess),
        reason: sourceState.reason,
        required_execution_mode: sourceState.required_execution_mode,
        required_module_state: sourceState.required_module_state,
        required_org_state: sourceState.required_org_state,
        required_permission: sourceState.required_permission,
        route_bound: routeBound,
        route_namespace: record.route_namespace,
        sidebar_state: sidebarStateForState(state),
        state,
        unlock_condition: sourceState.unlock_condition,
      };

      if (!owner && record.owner_only) {
        return {
          ...item,
          can_enter: false,
          org_visibility: "hidden" as const,
          sidebar_state: "hidden" as const,
          state: "hidden" as const,
        };
      }

      return item;
    })
    .sort((left, right) => {
      const groupDelta = groupOrder(left.nav_group) - groupOrder(right.nav_group);
      if (groupDelta !== 0) {
        return groupDelta;
      }
      if (left.nav_order !== right.nav_order) {
        return left.nav_order - right.nav_order;
      }
      return left.label.localeCompare(right.label);
    });

  const sidebarItems = items.filter(
    (item) => item.route_bound && item.sidebar_state !== "hidden",
  );
  const grouped = new Map<string, ProductCapabilityItem[]>();
  for (const item of sidebarItems) {
    const groupItems = grouped.get(item.nav_group) ?? [];
    groupItems.push(item);
    grouped.set(item.nav_group, groupItems);
  }
  const groups = Array.from(grouped.entries())
    .map(([label, groupItems]) => ({ items: groupItems, label }))
    .sort((left, right) => groupOrder(left.label) - groupOrder(right.label));

  return {
    byModuleKey: new Map(items.map((item) => [item.module_key, item])),
    executionState,
    groups,
    items,
    orgContext: orgContext({
      moduleAccessItems,
      moduleAccessUnknown,
      role,
    }),
    permissionSnapshot: permissionSnapshot(permissions),
    sidebarItems,
  };
}

export function findCapabilityForPath(
  pathname: string,
  items: readonly ProductCapabilityItem[],
) {
  const normalizedPath = pathname === "/" ? "/" : pathname.replace(/\/+$/, "");
  const matches = items.filter((item) => {
    const namespace =
      item.route_namespace === "/"
        ? "/"
        : item.route_namespace.replace(/\/+$/, "");
    return (
      normalizedPath === namespace ||
      (namespace !== "/" && normalizedPath.startsWith(`${namespace}/`))
    );
  });

  return (
    matches.sort(
      (left, right) =>
        right.route_namespace.length - left.route_namespace.length,
    )[0] ?? null
  );
}
