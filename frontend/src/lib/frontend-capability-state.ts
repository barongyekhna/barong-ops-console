import {
  Archive,
  Bot,
  Boxes,
  Building2,
  CircleAlert,
  ClipboardCheck,
  Database,
  FileText,
  LayoutDashboard,
  LockKeyhole,
  Package,
  Settings,
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
import {
  navigationGroups,
  navigationItems,
  navigationModuleRecords,
} from "@/lib/navigation";
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
  source: "/modules/me" | "frontend_ui_state";
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
  Building2,
  CircleAlert,
  ClipboardCheck,
  Database,
  FileText,
  LayoutDashboard,
  LockKeyhole,
  Package,
  Settings,
  UserRoundCog,
  Workflow,
};

const GROUP_ORDER = new Map([
  ["Users & Organizations", 10],
  ["Business Modules", 20],
  ["System Modules", 30],
  ["Extensions", 40],
  ["Core", 10],
  ["Operations", 20],
  ["System", 30],
  ["Registry", 40],
  ["Governance", 50],
]);

const PRODUCT_NAVIGATION_GROUPS = new Map<string, string>([
  ["admin.users", "Users & Organizations"],
  ["admin.organizations", "Users & Organizations"],
  ["admin.permissions", "Users & Organizations"],
  ["business.approvals", "Business Modules"],
  ["business.reviews", "Business Modules"],
  ["business.artifacts", "Business Modules"],
  ["core.dashboard", "System Modules"],
  ["admin.modules", "System Modules"],
  ["admin.settings", "System Modules"],
  ["system.errors", "System Modules"],
  ["system.memory_events", "System Modules"],
  ["system.operation_logs", "System Modules"],
  ["admin.agents", "Extensions"],
  ["business.products", "Extensions"],
]);

const PRODUCT_NAVIGATION_LABELS = new Map<string, string>([
  ["admin.users", "Users"],
  ["admin.organizations", "Organizations"],
  ["admin.permissions", "Permissions"],
  ["business.approvals", "Approvals"],
  ["business.reviews", "Reviews"],
  ["business.artifacts", "Artifacts"],
  ["core.dashboard", "Dashboard"],
  ["admin.modules", "Modules"],
  ["admin.settings", "Settings"],
  ["system.errors", "Errors"],
  ["system.memory_events", "Memory Events"],
  ["system.operation_logs", "Logs"],
  ["admin.agents", "Agents"],
  ["business.products", "Products"],
]);

const PRODUCT_NAVIGATION_ORDER = new Map<string, number>([
  ["admin.users", 10],
  ["admin.organizations", 20],
  ["admin.permissions", 30],
  ["business.approvals", 10],
  ["business.reviews", 20],
  ["business.artifacts", 30],
  ["core.dashboard", 10],
  ["admin.modules", 20],
  ["admin.settings", 30],
  ["system.errors", 40],
  ["system.memory_events", 50],
  ["system.operation_logs", 60],
  ["admin.agents", 10],
  ["business.products", 20],
]);

const INTERNAL_EXERCISE_MODULE_KEY = [
  "experimental",
  ["foun", "dation_", "de", "mo"].join(""),
].join(".");

export const PRODUCT_HIDDEN_MODULE_KEYS = new Set([
  INTERNAL_EXERCISE_MODULE_KEY,
  "integration.n8n_test_bridge",
]);

const routeByModuleKey = new Map(
  navigationModuleRecords.map((record) => [record.module_key, record]),
);

const UI_ONLY_LIVE_GATE: LiveGateRuntimeState = {
  active_policy_count: 0,
  blocked_reason: "Execution metadata is owned by AdapterAccessProvider.",
  canary_state: "not_configured",
  execution_mode: "mock",
  live_gate_status: "blocked",
  production_ready: false,
  readiness_passed: false,
  rollout_percentage: 0,
  source: "frontend_ui_state",
};

function isOwnerFullAccess(
  permissions: { is_owner_full_access?: boolean } | null | undefined,
) {
  return permissions?.is_owner_full_access === true;
}

function isSuperAdminVisibleAdminModule(role: string, moduleKey: string) {
  return (
    role === "super_admin" &&
    (moduleKey === "admin.users" || moduleKey === "admin.permissions")
  );
}

function isOrganizationListModule(moduleKey: string) {
  return moduleKey === "admin.organizations";
}

function isPermissionManagementModule(moduleKey: string) {
  return moduleKey === "admin.permissions";
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

function stateFromStaticNavigation(
  record: ModuleAwareNavigationRecord,
): ProductCapabilityStateName {
  if (PRODUCT_HIDDEN_MODULE_KEYS.has(record.module_key)) {
    return "hidden";
  }
  if (record.status === "adapter_pending") {
    return "adapter_pending";
  }
  if (
    record.status === "planned" ||
    record.status === "disabled" ||
    record.status === "unavailable" ||
    record.status === "deprecated"
  ) {
    return "partial";
  }
  return "allowed";
}

function staticCapabilityReason(state: ProductCapabilityStateName) {
  if (state === "hidden") {
    return "This product area is not part of the current navigation.";
  }
  if (state === "adapter_pending") {
    return "This product area is waiting for adapter metadata.";
  }
  if (state === "partial") {
    return "This product area is visible while metadata is loaded by its owner provider.";
  }
  return "This product area is available in the current navigation.";
}

export function buildFrontendUiCapabilityGraph({
  authStatus,
  role,
}: {
  authStatus: "checking" | "authenticated" | "unauthenticated";
  role: string;
}): FrontendCapabilityGraph {
  const owner = role === "owner";
  const executionState = deriveFrontendExecutionState({
    adapterAccessItems: [],
    executionProviderAccessItems: [],
    liveGate: UI_ONLY_LIVE_GATE,
  });
  const items = navigationGroups
    .flatMap((group) =>
      group.items.map((record) => {
        const hiddenPermissionModule =
          authStatus === "authenticated" &&
          isPermissionManagementModule(record.module_key) &&
          role !== "owner" &&
          role !== "super_admin";
        const state = hiddenPermissionModule
          ? "hidden"
          : stateFromStaticNavigation(record);
        const reason = staticCapabilityReason(state);
        const routeBound = Boolean(routeByModuleKey.get(record.module_key));
        const item: ProductCapabilityItem = {
          adapter_state: "owned_by_adapter_provider",
          api_binding: {
            adapter_bindings: [],
            api_bound: false,
            api_namespace: "owned_by_module_provider",
            no_api: true,
            route_bound: routeBound,
            route_namespace: record.route_namespace,
          },
          approval_state: executionState.approval_state,
          badge: badgeForState(state),
          blocked_reason: reason,
          can_enter:
            authStatus === "authenticated" &&
            routeBound &&
            state !== "hidden",
          canary_state: executionState.canary_state,
          description: "",
          execution_mode: executionState.execution_mode,
          href: record.href,
          icon: record.icon ?? Boxes,
          label: record.label,
          live_gate_status: executionState.live_gate_status,
          module_key: record.module_key,
          module_status: record.status ?? "unknown",
          nav_group: group.label,
          nav_order: routeOrder(record, null),
          org_visibility:
            authStatus === "authenticated" ? "visible" : "unknown",
          permission_state:
            authStatus === "authenticated" ? "available" : "unknown",
          provider_state: "owned_by_adapter_provider",
          reason,
          required_execution_mode:
            "Execution metadata is loaded by AdapterAccessProvider.",
          required_module_state:
            record.status ?? "Module metadata is loaded by ModuleAccessProvider.",
          required_org_state:
            authStatus === "authenticated"
              ? "Authenticated workspace identity."
              : "Authenticated identity is required.",
          required_permission:
            record.required_permission ?? "No additional permission required.",
          route_bound: routeBound,
          route_namespace: record.route_namespace,
          sidebar_state: sidebarStateForState(state),
          state,
          unlock_condition:
            state === "allowed"
              ? "Open this product area."
              : "Wait for the owning metadata provider to report availability.",
        };

        return item;
      }),
    )
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
    orgContext: {
      hidden_modules: items.length - sidebarItems.length,
      reason:
        authStatus === "authenticated"
          ? "Workspace UI state is derived from authenticated identity."
          : "Workspace UI state is waiting for authenticated identity.",
      role,
      source: "frontend_ui_state",
      state: authStatus === "authenticated" ? "active" : "unknown",
      visible_modules: sidebarItems.length,
    },
    permissionSnapshot: {
      is_owner_full_access: owner,
      permission_count: owner ? 1 : 0,
      permissions: owner ? ["*"] : [],
      source: "/auth/me",
    },
    sidebarItems,
  };
}

function routeIcon(record: ModuleAwareNavigationRecord, manifest: ModuleManifest | null) {
  return record.icon ?? ICONS[manifest?.navigation.icon ?? ""] ?? Boxes;
}

function routeLabel(record: ModuleAwareNavigationRecord, manifest: ModuleManifest | null) {
  const productLabel = PRODUCT_NAVIGATION_LABELS.get(record.module_key);
  if (productLabel) {
    return productLabel;
  }
  return manifest?.navigation.label || manifest?.display_name || record.label;
}

function routeGroup(record: ModuleAwareNavigationRecord, manifest: ModuleManifest | null) {
  const productGroup = PRODUCT_NAVIGATION_GROUPS.get(record.module_key);
  if (productGroup) {
    return productGroup;
  }
  if (manifest?.navigation.group) {
    if (manifest.navigation.group === "Overview") {
      return "System";
    }
    if (manifest.module_key === "system.operation_logs") {
      return "Operations";
    }
    return manifest.navigation.group;
  }
  return record.category === "core" ? "System" : "Operations";
}

function routeOrder(record: ModuleAwareNavigationRecord, manifest: ModuleManifest | null) {
  const productOrder = PRODUCT_NAVIGATION_ORDER.get(record.module_key);
  if (productOrder !== undefined) {
    return productOrder;
  }
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
    reason: "This product area is available for the current workspace.",
    required_execution_mode: executionRequired
      ? "Actions must be enabled for this workspace."
      : "View access is available.",
    required_module_state: manifest?.status ?? record.status ?? "enabled",
    required_org_state: "Active organization access.",
    required_permission: requiredPermission,
    state: "allowed" as ProductCapabilityStateName,
    unlock_condition: "Open this product area.",
  };

  if (PRODUCT_HIDDEN_MODULE_KEYS.has(record.module_key)) {
    return {
      ...base,
      reason: "This feature is not part of the current product navigation.",
      state: "hidden" as const,
      unlock_condition: "Use an available product area from the sidebar.",
    };
  }

  if (navigationState.isHidden) {
    if (record.denied_behavior === "show_locked") {
      return {
        ...base,
        reason:
          navigationState.reason ||
          "Your account does not have access to this product area.",
        state: "forbidden" as const,
        unlock_condition: "Ask an owner to grant the required access.",
      };
    }

    return {
      ...base,
      reason:
        navigationState.reason ||
        "This product area is not visible for the current workspace.",
      state: "hidden" as const,
      unlock_condition: "Ask an owner to review workspace access.",
    };
  }

  if (navigationState.isLocked) {
    return {
      ...base,
      reason:
        navigationState.reason ||
        "Your account does not have access to this product area.",
      state: "forbidden" as const,
      unlock_condition: "Ask an owner to grant the required access.",
    };
  }

  if (!routeBound) {
    return {
      ...base,
      reason: "This feature is not connected to a product page yet.",
      state: "partial" as const,
      unlock_condition: "Use an available product area from the sidebar.",
    };
  }

  if (registryUnavailable && !manifest) {
    return {
      ...base,
      reason: "Workspace product areas could not be refreshed.",
      state: "partial" as const,
      unlock_condition: "Refresh the page or try again later.",
    };
  }

  if (navigationState.moduleAccessUnknown) {
    return {
      ...base,
      reason:
        navigationState.reason ||
        "Workspace access could not be confirmed.",
      state: "partial" as const,
      unlock_condition: "Refresh the page or contact an owner.",
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
        "This feature is still being prepared.",
      required_execution_mode: "Actions must be enabled before use.",
      state: "adapter_pending" as const,
      unlock_condition: "Check back after setup is complete.",
    };
  }

  if (adapter?.hidden) {
    return {
      ...base,
      reason: adapter.reason || "This feature is hidden for the current workspace.",
      state: "hidden" as const,
      unlock_condition: "Ask an owner to review workspace access.",
    };
  }

  if (adapter?.locked) {
    return {
      ...base,
      reason: adapter.reason || "Your account does not have access to this feature.",
      state: "forbidden" as const,
      unlock_condition: "Ask an owner to grant the required access.",
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
        "This feature is not fully available yet.",
      required_execution_mode: "Actions are not available yet.",
      state: "partial" as const,
      unlock_condition: "Use the available product areas while setup continues.",
    };
  }

  if (executionRequired && executionState.live_gate_status === "backend_unavailable") {
    return {
      ...base,
      reason: "Action readiness could not be confirmed.",
      required_execution_mode: "Action readiness must be available.",
      state: "backend_unavailable" as const,
      unlock_condition: "Refresh the page or try again later.",
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
        "Actions are not enabled for this workspace.",
      required_execution_mode: "Actions must be enabled before use.",
      state: "no_execution" as const,
      unlock_condition: "Ask an owner to finish feature setup.",
    };
  }

  if (
    executionRequired &&
    (executionProviderAccessUnknown || hasMockProvider(providerAccess, providerContracts))
  ) {
    return {
      ...base,
      reason: executionProviderAccessUnknown
        ? "Action readiness could not be confirmed."
        : "This feature is available only as a preview.",
      required_execution_mode: "Actions must be enabled before use.",
      state: executionProviderAccessUnknown ? "partial" as const : "mock" as const,
      unlock_condition: "Ask an owner to finish feature setup.",
    };
  }

  if (adapterAccessUnknown && manifest?.module_adapter_required) {
    return {
      ...base,
      reason: "Feature setup could not be confirmed.",
      required_execution_mode: "Feature setup must be confirmed.",
      state: "backend_unavailable" as const,
      unlock_condition: "Refresh the page or try again later.",
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

function ownerCapabilityItem({
  item,
  permissionBlocked,
  record,
  routeBound,
}: {
  item: ProductCapabilityItem;
  permissionBlocked: boolean;
  record: ModuleAwareNavigationRecord;
  routeBound: boolean;
}): ProductCapabilityItem {
  const state = permissionBlocked ? "allowed" : item.state;

  return {
    ...item,
    badge: permissionBlocked ? badgeForState(state) : item.badge,
    can_enter: routeBound && state !== "hidden",
    org_visibility: "visible",
    permission_state: "available",
    reason: permissionBlocked
      ? "Owner full access bypasses frontend permission checks for this product area."
      : item.reason,
    required_permission: permissionBlocked
      ? record.required_permission ?? "Owner full access."
      : item.required_permission,
    sidebar_state: permissionBlocked
      ? sidebarStateForState(state)
      : item.sidebar_state,
    state,
    unlock_condition: permissionBlocked
      ? "Open this product area."
      : item.unlock_condition,
  };
}

function organizationListCapabilityItem({
  item,
  routeBound,
}: {
  item: ProductCapabilityItem;
  routeBound: boolean;
}): ProductCapabilityItem {
  return {
    ...item,
    badge: null,
    can_enter: routeBound,
    org_visibility: "visible",
    permission_state: "available",
    reason: "Organization list is visible to every authenticated user.",
    required_permission: "Authenticated user session.",
    sidebar_state: "allowed",
    state: "allowed",
    unlock_condition: "Open the organization list.",
  };
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
      reason: "Workspace organization access is unavailable or incomplete.",
      role,
      source: "/modules/me",
      state: "unknown",
      visible_modules: moduleAccessItems.filter((item) => item.visible).length,
    };
  }

  return {
    hidden_modules: moduleAccessItems.filter((item) => item.hidden).length,
    reason: "Workspace organization access is available.",
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
  const sourceMap = new Map<
    string,
    {
      manifest: ModuleManifest | null;
      moduleKey: string;
      record: ModuleAwareNavigationRecord;
    }
  >();

  for (const record of navigationModuleRecords) {
    sourceMap.set(record.module_key, {
      manifest: registryByModule.get(record.module_key) ?? null,
      moduleKey: record.module_key,
      record,
    });
  }

  for (const manifest of registryItems) {
    if (!sourceMap.has(manifest.module_key)) {
      sourceMap.set(manifest.module_key, {
        manifest,
        moduleKey: manifest.module_key,
        record: routeByModuleKey.get(manifest.module_key) ?? recordFromManifest(manifest),
      });
    }
  }

  const sources = Array.from(sourceMap.values());
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

      if (owner || isSuperAdminVisibleAdminModule(role, moduleKey)) {
        const permissionBlocked =
          navigationState.isHidden ||
          navigationState.isLocked ||
          adapterAccess?.hidden === true ||
          adapterAccess?.locked === true;

        return ownerCapabilityItem({
          item,
          permissionBlocked,
          record,
          routeBound,
        });
      }

      if (!owner && isPermissionManagementModule(moduleKey)) {
        return {
          ...item,
          badge: null,
          can_enter: false,
          org_visibility: "hidden" as const,
          permission_state: "hidden" as const,
          reason: "This product area is hidden for the current role.",
          required_permission: "Owner or super admin role.",
          sidebar_state: "hidden" as const,
          state: "hidden" as const,
          unlock_condition: "Use an available product area from the sidebar.",
        };
      }

      if (isOrganizationListModule(moduleKey)) {
        return organizationListCapabilityItem({
          item,
          routeBound,
        });
      }

      if (!owner && record.owner_only) {
        return {
          ...item,
          can_enter: false,
          badge: "locked" as const,
          org_visibility: "visible" as const,
          permission_state: "locked" as const,
          reason: "Owner access is required for this product area.",
          required_permission:
            record.required_permission ?? "Owner access required.",
          sidebar_state: "forbidden" as const,
          state: "forbidden" as const,
          unlock_condition: "Ask an owner to grant the required access.",
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
