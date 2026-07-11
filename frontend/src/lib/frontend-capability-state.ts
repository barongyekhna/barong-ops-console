import {
  Bot,
  Boxes,
  Building2,
  CircleAlert,
  ClipboardCheck,
  Database,
  FileText,
  GitBranch,
  LayoutDashboard,
  LockKeyhole,
  PackageSearch,
  Settings,
  UserRoundCog,
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
import { isOwnerRole, isSuperAdminRole, normalizeRole } from "@/lib/roles";
import { getModuleDisplayName } from "@/lib/i18n";

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
  Bot,
  Boxes,
  Building2,
  CircleAlert,
  ClipboardCheck,
  Database,
  FileText,
  GitBranch,
  LayoutDashboard,
  LockKeyhole,
  PackageSearch,
  Settings,
  UserRoundCog,
};

const GROUP_ORDER = new Map([
  ["账号与组织", 10],
  ["业务处理", 20],
  ["系统管理", 30],
  ["扩展能力", 40],
  ["Core", 10],
  ["Operations", 20],
  ["System", 30],
  ["Registry", 40],
  ["Governance", 50],
]);

const PRODUCT_NAVIGATION_GROUPS = new Map<string, string>([
  ["admin.users", "账号与组织"],
  ["admin.organizations", "账号与组织"],
  ["admin.permissions", "账号与组织"],
  ["k.product_knowledge", "业务处理"],
  ["r.analysis", "业务处理"],
  ["r.warehouse", "业务处理"],
  ["business.approvals", "业务处理"],
  ["business.reviews", "业务处理"],
  ["core.dashboard", "系统管理"],
  ["admin.modules", "系统管理"],
  ["admin.settings", "系统管理"],
  ["system.errors", "系统管理"],
  ["system.memory_events", "系统管理"],
  ["system.operation_logs", "系统管理"],
  ["admin.agents", "扩展能力"],
]);

const PRODUCT_NAVIGATION_LABELS = new Map<string, string>([
  ["admin.users", "用户管理"],
  ["admin.organizations", "组织管理"],
  ["admin.permissions", "权限管理"],
  ["k.product_knowledge", "产品知识库"],
  ["r.analysis", "R-A 产品分析中心"],
  ["r.warehouse", "R-W 产品数据仓库"],
  ["business.approvals", "审批"],
  ["business.reviews", "审批审计"],
  ["core.dashboard", "控制台"],
  ["admin.modules", "模块控制"],
  ["admin.settings", "设置"],
  ["system.errors", "异常记录"],
  ["system.memory_events", "运行记录"],
  ["system.operation_logs", "操作记录"],
  ["admin.agents", "自动化助手"],
]);

const PRODUCT_NAVIGATION_ORDER = new Map<string, number>([
  ["admin.users", 10],
  ["admin.organizations", 20],
  ["admin.permissions", 30],
  ["k.product_knowledge", 10],
  ["r.warehouse", 12],
  ["r.analysis", 13],
  ["business.approvals", 10],
  ["business.reviews", 20],
  ["core.dashboard", 10],
  ["admin.modules", 20],
  ["admin.settings", 40],
  ["system.errors", 50],
  ["system.memory_events", 60],
  ["system.operation_logs", 70],
  ["admin.agents", 10],
]);

const INTERNAL_EXERCISE_MODULE_KEY = [
  "experimental",
  ["foun", "dation_", "de", "mo"].join(""),
].join(".");
const K_PRODUCT_KNOWLEDGE_MODULE_KEY = "k.product_knowledge";
const I_IMAGE_SYSTEM_MODULE_KEY = "i.image_system";
const P_UPLOAD_MODULE_KEY = "p.upload";
const R_ANALYSIS_MODULE_KEY = "r.analysis";
const OWNER_ONLY_ADMIN_MODULE_KEYS = new Set([
  "admin.modules",
]);

export const PRODUCT_HIDDEN_MODULE_KEYS = new Set([
  "admin.agents",
  "admin.key_management",
  "admin.settings",
  INTERNAL_EXERCISE_MODULE_KEY,
  "integration.n8n_test_bridge",
  "system.errors",
  "system.memory_events",
  "system.operation_logs",
]);

const routeByModuleKey = new Map(
  navigationModuleRecords.map((record) => [record.module_key, record]),
);

const UI_ONLY_LIVE_GATE: LiveGateRuntimeState = {
  active_policy_count: 0,
  blocked_reason: "功能状态正在由系统汇总。",
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
    isSuperAdminRole(role) &&
    !OWNER_ONLY_ADMIN_MODULE_KEYS.has(moduleKey) &&
    !PRODUCT_HIDDEN_MODULE_KEYS.has(moduleKey)
  );
}

function isOwnerOnlyModule(
  moduleKey: string,
  record: ModuleAwareNavigationRecord,
  manifest: ModuleManifest | null,
) {
  return (
    OWNER_ONLY_ADMIN_MODULE_KEYS.has(moduleKey) ||
    record.owner_only === true ||
    manifest?.navigation.owner_only === true
  );
}

function isApprovalModule(moduleKey: string) {
  return moduleKey === "business.approvals";
}

function isReviewAuditModule(moduleKey: string) {
  return moduleKey === "business.reviews";
}

function canSeeReviewAudit(role: string) {
  return isOwnerRole(role) || isSuperAdminRole(role);
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
    return "需要管理员开通访问权限。";
  }
  if (record.required_permission) {
    return "需要管理员开通访问权限。";
  }
  return "当前账号可访问。";
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
    return "该功能区暂未开放。";
  }
  if (state === "adapter_pending") {
    return "该功能区仍在配置中。";
  }
  if (state === "partial") {
    return "该功能区暂时不可用。";
  }
  return "该功能区可用。";
}

export function buildFrontendUiCapabilityGraph({
  authStatus,
  role,
}: {
  authStatus: "checking" | "authenticated" | "unauthenticated";
  role: string;
}): FrontendCapabilityGraph {
  const normalizedRole = normalizeRole(role);
  const owner = isOwnerRole(normalizedRole);
  const executionState = deriveFrontendExecutionState({
    adapterAccessItems: [],
    executionProviderAccessItems: [],
    liveGate: UI_ONLY_LIVE_GATE,
  });
  const items = navigationGroups
    .flatMap((group) =>
      group.items.map((record) => {
        const ownerOnlyModule = isOwnerOnlyModule(
          record.module_key,
          record,
          null,
        );
        const hiddenPermissionModule =
          authStatus === "authenticated" &&
          isPermissionManagementModule(record.module_key) &&
          !isOwnerRole(normalizedRole) &&
          !isSuperAdminRole(normalizedRole);
        const hiddenReviewAuditModule =
          authStatus === "authenticated" &&
          isReviewAuditModule(record.module_key) &&
          !canSeeReviewAudit(normalizedRole);
        const roleVisibleModule =
          authStatus === "authenticated" &&
          (owner ||
            isSuperAdminVisibleAdminModule(normalizedRole, record.module_key) ||
            (isSuperAdminRole(normalizedRole) &&
              isApprovalModule(record.module_key)) ||
            (canSeeReviewAudit(normalizedRole) &&
              isReviewAuditModule(record.module_key)));
        const state = ownerOnlyModule && !owner
          ? "hidden"
          : hiddenPermissionModule
          ? "hidden"
          : hiddenReviewAuditModule
            ? "hidden"
            : roleVisibleModule
              ? "allowed"
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
            "操作状态由系统自动确认。",
          required_module_state:
            state === "allowed" ? "功能区可用。" : "功能区暂不可用。",
          required_org_state:
            authStatus === "authenticated"
              ? "当前账号已登录。"
              : "请先登录。",
          required_permission:
            record.required_permission ? "需要管理员开通访问权限。" : "当前账号可访问。",
          route_bound: routeBound,
          route_namespace: record.route_namespace,
          sidebar_state: sidebarStateForState(state),
          state,
          unlock_condition:
            state === "allowed"
              ? "打开功能区。"
              : "等待管理员完成配置。",
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
  const visibleSidebarItems = items.filter(
    (item) => item.route_bound && item.sidebar_state !== "hidden",
  );
  const sidebarItems = owner || authStatus !== "authenticated"
    ? visibleSidebarItems
    : [];
  const grouped = new Map<string, ProductCapabilityItem[]>();
  if (owner || authStatus !== "authenticated") {
    for (const item of sidebarItems) {
      const groupItems = grouped.get(item.nav_group) ?? [];
      groupItems.push(item);
      grouped.set(item.nav_group, groupItems);
    }
  } else {
    grouped.set("Modules", sidebarItems);
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
          ? "工作台已按当前账号加载。"
          : "工作台等待登录后加载。",
      role: normalizedRole,
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
  return getModuleDisplayName(
    record.module_key,
    manifest?.navigation.label || manifest?.display_name || record.label,
  );
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

// 这些模块的执行门禁是"动作级"的（真正调用生成/上架时才 resolve key 与
// gate），不需要预注册 execution surface —— 否则会被误判成 no_execution
// 而在侧边栏变暗（K 最早就是这么豁免的，I/P 同理）。
const ACTION_SCOPED_EXECUTION_GATE_MODULE_KEYS = new Set([
  K_PRODUCT_KNOWLEDGE_MODULE_KEY,
  I_IMAGE_SYSTEM_MODULE_KEY,
  P_UPLOAD_MODULE_KEY,
]);

function usesActionScopedExecutionGate(moduleKey: string | undefined) {
  return Boolean(
    moduleKey && ACTION_SCOPED_EXECUTION_GATE_MODULE_KEYS.has(moduleKey),
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
  if (usesActionScopedExecutionGate(manifest?.module_key ?? adapter?.module_key)) {
    return false;
  }

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
    reason: "该功能区可用。",
    required_execution_mode: executionRequired
      ? "需要先启用相关操作能力。"
      : "可查看。",
    required_module_state: "功能区可用。",
    required_org_state: "当前组织可访问。",
    required_permission: requiredPermission,
    state: "allowed" as ProductCapabilityStateName,
    unlock_condition: "打开功能区。",
  };

  if (PRODUCT_HIDDEN_MODULE_KEYS.has(record.module_key)) {
    return {
      ...base,
      reason: "该功能区暂未开放。",
      state: "hidden" as const,
      unlock_condition: "请使用左侧已开放功能。",
    };
  }

  if (navigationState.isHidden) {
    if (record.denied_behavior === "show_locked") {
      return {
        ...base,
        reason: "当前账号无权访问该功能区。",
        state: "forbidden" as const,
        unlock_condition: "请联系owner开通访问权限。",
      };
    }

    return {
      ...base,
      reason: "该功能区对当前账号不可见。",
      state: "hidden" as const,
      unlock_condition: "请联系owner确认访问范围。",
    };
  }

  if (navigationState.isLocked) {
    return {
      ...base,
      reason: "当前账号无权访问该功能区。",
      state: "forbidden" as const,
      unlock_condition: "请联系owner开通访问权限。",
    };
  }

  if (!routeBound) {
    return {
      ...base,
      reason: "该能力暂未接入产品页面。",
      state: "partial" as const,
      unlock_condition: "请使用左侧已开放功能。",
    };
  }

  if (registryUnavailable && !manifest) {
    return {
      ...base,
      reason: "功能区信息暂时无法刷新。",
      state: "partial" as const,
      unlock_condition: "请刷新页面或稍后重试。",
    };
  }

  if (navigationState.moduleAccessUnknown) {
    return {
      ...base,
      reason: "暂时无法确认当前账号访问范围。",
      state: "partial" as const,
      unlock_condition: "请刷新页面或联系owner。",
    };
  }

  if (
    navigationState.accessState === "adapter_pending" ||
    manifest?.status === "adapter_pending" ||
    adapter?.adapter_access_state === "adapter_pending"
  ) {
    return {
      ...base,
      reason: "该功能区仍在配置中。",
      required_execution_mode: "需要先启用相关操作能力。",
      state: "adapter_pending" as const,
      unlock_condition: "请等待管理员完成配置。",
    };
  }

  if (adapter?.hidden) {
    return {
      ...base,
      reason: "该功能区对当前组织不可见。",
      state: "hidden" as const,
      unlock_condition: "请联系owner确认访问范围。",
    };
  }

  if (adapter?.locked) {
    return {
      ...base,
      reason: "当前账号无权访问该功能区。",
      state: "forbidden" as const,
      unlock_condition: "请联系owner开通访问权限。",
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
      reason: "该功能区暂时不可用。",
      required_execution_mode: "操作能力暂不可用。",
      state: "partial" as const,
      unlock_condition: "请先使用已开放功能。",
    };
  }

  if (executionRequired && executionState.live_gate_status === "backend_unavailable") {
    return {
      ...base,
      reason: "暂时无法确认操作状态。",
      required_execution_mode: "操作状态需要可用。",
      state: "backend_unavailable" as const,
      unlock_condition: "请刷新页面或稍后重试。",
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
      reason: "该功能区的操作能力尚未启用。",
      required_execution_mode: "需要先启用操作能力。",
      state: "no_execution" as const,
      unlock_condition: "请联系owner完成配置。",
    };
  }

  if (
    executionRequired &&
    (executionProviderAccessUnknown || hasMockProvider(providerAccess, providerContracts))
  ) {
    return {
      ...base,
      reason: executionProviderAccessUnknown
        ? "暂时无法确认操作状态。"
        : "该功能区目前仅可预览。",
      required_execution_mode: "需要先启用操作能力。",
      state: executionProviderAccessUnknown ? "partial" as const : "mock" as const,
      unlock_condition: "请联系owner完成配置。",
    };
  }

  if (adapterAccessUnknown && manifest?.module_adapter_required) {
    return {
      ...base,
      reason: "暂时无法确认功能配置。",
      required_execution_mode: "需要确认功能配置。",
      state: "backend_unavailable" as const,
      unlock_condition: "请刷新页面或稍后重试。",
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
  moduleKey,
  navigationState,
  routeBound,
  state,
}: {
  executionRequired: boolean;
  moduleKey: string;
  navigationState: ModuleNavigationState;
  routeBound: boolean;
  state: ProductCapabilityStateName;
}) {
  if (moduleKey === R_ANALYSIS_MODULE_KEY) {
    return routeBound && state !== "hidden" && state !== "forbidden";
  }
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
      ? "owner拥有全部访问权限。"
      : item.reason,
    required_permission: permissionBlocked
      ? "owner全部权限。"
      : item.required_permission,
    sidebar_state: permissionBlocked
      ? sidebarStateForState(state)
      : item.sidebar_state,
    state,
    unlock_condition: permissionBlocked
      ? "打开功能区。"
      : item.unlock_condition,
  };
}

function superAdminVisibleCapabilityItem({
  item,
  routeBound,
  reason,
  requiredPermission,
  unlockCondition,
}: {
  item: ProductCapabilityItem;
  routeBound: boolean;
  reason: string;
  requiredPermission: string;
  unlockCondition: string;
}): ProductCapabilityItem {
  return {
    ...item,
    badge: null,
    can_enter: routeBound,
    org_visibility: "visible",
    permission_state: "available",
    reason,
    required_permission: requiredPermission,
    sidebar_state: "allowed",
    state: "allowed",
    unlock_condition: unlockCondition,
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
    reason: "已登录账号可以查看组织列表。",
    required_permission: "当前账号已登录。",
    sidebar_state: "allowed",
    state: "allowed",
    unlock_condition: "打开组织管理。",
  };
}

function reviewAuditCapabilityItem({
  item,
  routeBound,
  visible,
}: {
  item: ProductCapabilityItem;
  routeBound: boolean;
  visible: boolean;
}): ProductCapabilityItem {
  if (!visible) {
    return {
      ...item,
      badge: null,
      can_enter: false,
      org_visibility: "hidden",
      permission_state: "hidden",
      reason: "该功能区对当前角色不可见。",
      required_permission: "需要owner或组织管理员权限。",
      sidebar_state: "hidden",
      state: "hidden",
      unlock_condition: "请使用左侧已开放功能。",
    };
  }

  return {
    ...item,
    badge: null,
    can_enter: routeBound,
    org_visibility: "visible",
    permission_state: "available",
    reason: "当前角色可查看审批审计。",
    required_permission: "需要owner或组织管理员权限。",
    sidebar_state: "allowed",
    state: "allowed",
    unlock_condition: "打开审批审计。",
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
      reason: "暂时无法确认组织访问范围。",
      role,
      source: "/modules/me",
      state: "unknown",
      visible_modules: moduleAccessItems.filter((item) => item.visible).length,
    };
  }

  return {
    hidden_modules: moduleAccessItems.filter((item) => item.hidden).length,
    reason: "组织访问范围已确认。",
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

  if (registryItems.length > 0) {
    for (const manifest of registryItems) {
      if (manifest.navigation.default_visible === false) {
        continue;
      }
      sourceMap.set(manifest.module_key, {
        manifest,
        moduleKey: manifest.module_key,
        record: routeByModuleKey.get(manifest.module_key) ?? recordFromManifest(manifest),
      });
    }
  }

  for (const record of navigationModuleRecords) {
    const existing = sourceMap.get(record.module_key);
    sourceMap.set(record.module_key, {
      manifest: existing?.manifest ?? registryByModule.get(record.module_key) ?? null,
      moduleKey: record.module_key,
      record,
    });
  }

  if (sourceMap.size === 0) {
    for (const record of navigationModuleRecords) {
      sourceMap.set(record.module_key, {
        manifest: registryByModule.get(record.module_key) ?? null,
        moduleKey: record.module_key,
        record,
      });
    }
  }

  const sources = Array.from(sourceMap.values());
  const normalizedRole = normalizeRole(role);
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
          moduleKey,
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

      if (!owner && isOwnerOnlyModule(moduleKey, record, manifest)) {
        return {
          ...item,
          badge: null,
          can_enter: false,
          org_visibility: "hidden" as const,
          permission_state: "hidden" as const,
          reason: "该功能区仅owner可见。",
          required_permission: "需要owner权限。",
          sidebar_state: "hidden" as const,
          state: "hidden" as const,
          unlock_condition: "请使用左侧已开放功能。",
        };
      }

      if (isReviewAuditModule(moduleKey)) {
        return reviewAuditCapabilityItem({
          item,
          routeBound,
          visible: owner || canSeeReviewAudit(normalizedRole),
        });
      }

      if (isSuperAdminRole(normalizedRole) && isApprovalModule(moduleKey)) {
        return superAdminVisibleCapabilityItem({
          item,
          reason: "组织管理员可查看本组织功能审批。",
          requiredPermission: "组织管理员权限。",
          routeBound,
          unlockCondition: "打开审批。",
        });
      }

      if (owner || isSuperAdminVisibleAdminModule(normalizedRole, moduleKey)) {
        const permissionBlocked =
          navigationState.isHidden ||
          navigationState.isLocked ||
          adapterAccess?.hidden === true ||
          adapterAccess?.locked === true;

        if (owner) {
          return ownerCapabilityItem({
            item,
            permissionBlocked,
            record,
            routeBound,
          });
        }

        return superAdminVisibleCapabilityItem({
          item,
          reason: "组织管理员可查看并管理本组织范围。",
          requiredPermission: "组织管理员权限。",
          routeBound,
          unlockCondition: "打开功能区。",
        });
      }

      if (!owner && isPermissionManagementModule(moduleKey)) {
        return {
          ...item,
          badge: null,
          can_enter: false,
          org_visibility: "hidden" as const,
          permission_state: "hidden" as const,
          reason: "该功能区对当前角色不可见。",
          required_permission: "需要owner或组织管理员权限。",
          sidebar_state: "hidden" as const,
          state: "hidden" as const,
          unlock_condition: "请使用左侧已开放功能。",
        };
      }

      if (isOrganizationListModule(moduleKey)) {
        return organizationListCapabilityItem({
          item,
          routeBound,
        });
      }

      if (!owner && !isSuperAdminRole(normalizedRole) && record.owner_only) {
        return {
          ...item,
          can_enter: false,
          badge: null,
          org_visibility: "hidden" as const,
          permission_state: "hidden" as const,
          reason: "该功能区需要owner权限。",
          required_permission: "需要owner权限。",
          sidebar_state: "hidden" as const,
          state: "hidden" as const,
          unlock_condition: "请使用左侧已开放功能。",
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

  const assignedVisibleModuleKeys = new Set(
    moduleAccessItems
      .filter((item) => item.visible && !item.hidden && !item.locked)
      .map((item) => item.module_key),
  );
  const visibleSidebarItems = items.filter(
    (item) => item.route_bound && item.sidebar_state !== "hidden",
  );
  const sidebarItems = owner
    ? visibleSidebarItems
    : visibleSidebarItems.filter(
        (item) =>
          assignedVisibleModuleKeys.has(item.module_key) &&
          !OWNER_ONLY_ADMIN_MODULE_KEYS.has(item.module_key),
      );
  const grouped = new Map<string, ProductCapabilityItem[]>();
  if (owner) {
    for (const item of sidebarItems) {
      const groupItems = grouped.get(item.nav_group) ?? [];
      groupItems.push(item);
      grouped.set(item.nav_group, groupItems);
    }
  } else {
    grouped.set("Modules", sidebarItems);
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
      role: normalizedRole,
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
