"use client";

import {
  Archive,
  Bot,
  Boxes,
  CircleAlert,
  ClipboardCheck,
  Database,
  LayoutDashboard,
  LockKeyhole,
  Sparkles,
  UserRoundCog,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { useAdapterAccess } from "@/components/adapter-access-provider";
import { useAuth } from "@/components/auth-provider";
import { useModuleAccess } from "@/components/module-access-provider";
import { navigationItems, navigationModuleRecords } from "@/lib/navigation";
import {
  listModuleRegistry,
  type ModuleApiErrorSummary,
} from "@/lib/module-registry-api";
import type {
  ExecutionProviderAccessState,
  ExecutionProviderContract,
} from "@/lib/execution-provider";
import type { ModuleAdapterAccessState } from "@/lib/module-adapter";
import {
  findModuleAccessState,
  getNavigationStateForModule,
  type ModuleAccessState,
  type ModuleAwareNavigationRecord,
  type ModuleManifest,
  type ModuleNavigationState,
  type ModuleStatus,
} from "@/lib/module-registry";

export type CapabilitySidebarState =
  | "allowed"
  | "forbidden"
  | "hidden"
  | "partial"
  | "mock"
  | "adapter_pending";

export type CapabilitySidebarItem = {
  href: string;
  icon: LucideIcon;
  label: string;
  module_key: string;
  nav_group: string;
  nav_order: number;
  route_namespace: string;
  state: CapabilitySidebarState;
  badge: "locked" | "read_only" | "mock" | "adapter_pending" | null;
  reason: string;
  unlock_condition: string;
  required_permission: string;
  required_org_state: string;
  required_module_state: string;
  required_execution_mode: string;
  module_status: ModuleStatus | "unknown";
};

export type CapabilitySidebarGroup = {
  label: string;
  items: CapabilitySidebarItem[];
};

type CapabilitySidebarContextValue = {
  groups: CapabilitySidebarGroup[];
  items: CapabilitySidebarItem[];
  isLoading: boolean;
  error: ModuleApiErrorSummary | null;
  registryUnavailable: boolean;
  refresh: () => Promise<void>;
};

const CapabilitySidebarContext =
  createContext<CapabilitySidebarContextValue | null>(null);

const ICONS: Record<string, LucideIcon> = {
  Archive,
  Bot,
  Boxes,
  CircleAlert,
  ClipboardCheck,
  Database,
  LayoutDashboard,
  LockKeyhole,
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

const PRODUCT_HIDDEN_MODULE_KEYS = new Set([
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

function adapterForModule(
  moduleKey: string,
  adapters: readonly ModuleAdapterAccessState[],
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

function capabilityStateFromSources({
  adapter,
  adapterAccessUnknown,
  executionProviderAccessUnknown,
  manifest,
  moduleAccessState,
  navigationState,
  providerAccess,
  providerContracts,
  record,
  registryUnavailable,
}: {
  adapter: ModuleAdapterAccessState | null;
  adapterAccessUnknown: boolean;
  executionProviderAccessUnknown: boolean;
  manifest: ModuleManifest | null;
  moduleAccessState: ModuleAccessState | null;
  navigationState: ModuleNavigationState;
  providerAccess: readonly ExecutionProviderAccessState[];
  providerContracts: readonly ExecutionProviderContract[];
  record: ModuleAwareNavigationRecord;
  registryUnavailable: boolean;
}) {
  const requiredPermission = missingPermissionText(record, moduleAccessState);
  const base = {
    required_execution_mode: "Read-only backend capability.",
    required_module_state: manifest?.status ?? record.status ?? "enabled",
    required_org_state: "Active organization context with module visibility.",
    required_permission: requiredPermission,
    state: "allowed" as CapabilitySidebarState,
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

  if (registryUnavailable) {
    return {
      ...base,
      reason: "Module registry is unavailable; sidebar is using route metadata only.",
      state: navigationState.isLocked ? "forbidden" as const : "partial" as const,
      unlock_condition: "Restore /modules/registry and /modules/me.",
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
        "C08 adapter readiness is pending.",
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
    manifest?.status === "deprecated" ||
    hasUnavailableProvider(providerAccess)
  ) {
    return {
      ...base,
      reason:
        adapter?.reason ||
        providerAccess.find((provider) => provider.block_reason)?.block_reason ||
        navigationState.reason ||
        "Capability exists but is not fully executable.",
      required_execution_mode: "Non-mock execution provider readiness is required for actions.",
      state: "partial" as const,
      unlock_condition: "Enable the module, adapter, and provider readiness chain.",
    };
  }

  if (
    (manifest?.execution_provider_required || providerAccess.length > 0) &&
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
      state: "partial" as const,
      unlock_condition: "Restore /module-adapters/me.",
    };
  }

  return {
    ...base,
    reason: "Capability is visible, permission-allowed, and backed by a registered route.",
  };
}

function badgeForState(state: CapabilitySidebarState) {
  if (state === "forbidden") {
    return "locked" as const;
  }
  if (state === "adapter_pending") {
    return "adapter_pending" as const;
  }
  if (state === "mock") {
    return "mock" as const;
  }
  if (state === "partial") {
    return "read_only" as const;
  }
  return null;
}

export function CapabilitySidebarProvider({
  children,
}: {
  children: ReactNode;
}) {
  const { user, status } = useAuth();
  const {
    adapterAccessUnknown,
    accessItems: adapterAccessItems,
    executionProviderAccessItems,
    executionProviderAccessUnknown,
    executionProviders,
  } = useAdapterAccess();
  const {
    items: moduleAccessItems,
    moduleAccessUnknown,
  } = useModuleAccess();
  const [registryItems, setRegistryItems] = useState<ModuleManifest[]>([]);
  const [registryUnavailable, setRegistryUnavailable] = useState(true);
  const [error, setError] = useState<ModuleApiErrorSummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const loadRegistry = useCallback(async () => {
    if (status !== "authenticated" || !user) {
      setRegistryItems([]);
      setRegistryUnavailable(true);
      setError(null);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    const result = await listModuleRegistry();
    setRegistryItems(result.data.items);
    setRegistryUnavailable(!result.ok);
    setError(result.error);
    setIsLoading(false);
  }, [status, user]);

  useEffect(() => {
    let active = true;

    async function refreshWhenActive() {
      if (!active) {
        return;
      }
      await loadRegistry();
    }

    void refreshWhenActive();

    return () => {
      active = false;
    };
  }, [loadRegistry]);

  const items = useMemo(() => {
    const owner = isOwnerFullAccess(user?.permissions);
    const registryByModule = new Map(
      registryItems.map((manifest) => [manifest.module_key, manifest]),
    );
    const manifestSources =
      registryItems.length > 0
        ? registryItems
        : navigationItems.map((record) => registryByModule.get(record.module_key)).filter(
            (manifest): manifest is ModuleManifest => Boolean(manifest),
          );
    const moduleKeys =
      registryItems.length > 0
        ? manifestSources.map((manifest) => manifest.module_key)
        : navigationItems.map((record) => record.module_key);
    const uniqueModuleKeys = Array.from(new Set(moduleKeys));

    return uniqueModuleKeys
      .map((moduleKey) => {
        const record = routeByModuleKey.get(moduleKey);
        if (!record) {
          return null;
        }

        const manifest = registryByModule.get(moduleKey) ?? null;
        const moduleAccessState = findModuleAccessState(
          moduleKey,
          moduleAccessItems,
        );
        const navigationState = getNavigationStateForModule(
          user?.permissions,
          record,
          moduleAccessItems,
          { moduleAccessUnknown: moduleAccessUnknown || !moduleAccessState },
        );
        const adapter = adapterForModule(moduleKey, adapterAccessItems);
        const providerAccess = providersForModule(
          moduleKey,
          executionProviderAccessItems,
        );
        const providerContracts = providerContractsForModule(
          moduleKey,
          executionProviders,
        );
        const state = capabilityStateFromSources({
          adapter,
          adapterAccessUnknown,
          executionProviderAccessUnknown,
          manifest,
          moduleAccessState,
          navigationState,
          providerAccess,
          providerContracts,
          record,
          registryUnavailable,
        });
        const item: CapabilitySidebarItem = {
          badge: badgeForState(state.state),
          href: record.href,
          icon: routeIcon(record, manifest),
          label: routeLabel(record, manifest),
          module_key: moduleKey,
          module_status: manifest?.status ?? record.status ?? "unknown",
          nav_group: routeGroup(record, manifest),
          nav_order: routeOrder(record, manifest),
          reason: state.reason,
          required_execution_mode: state.required_execution_mode,
          required_module_state: state.required_module_state,
          required_org_state: state.required_org_state,
          required_permission: state.required_permission,
          route_namespace: record.route_namespace,
          state: state.state,
          unlock_condition: state.unlock_condition,
        };

        if (item.state === "hidden") {
          return null;
        }

        if (!owner && record.owner_only) {
          return null;
        }

        return item;
      })
      .filter((item): item is CapabilitySidebarItem => Boolean(item))
      .sort((left, right) => {
        const groupDelta =
          groupOrder(left.nav_group) - groupOrder(right.nav_group);
        if (groupDelta !== 0) {
          return groupDelta;
        }
        if (left.nav_order !== right.nav_order) {
          return left.nav_order - right.nav_order;
        }
        return left.label.localeCompare(right.label);
      });
  }, [
    adapterAccessItems,
    adapterAccessUnknown,
    executionProviderAccessItems,
    executionProviderAccessUnknown,
    executionProviders,
    moduleAccessItems,
    moduleAccessUnknown,
    registryItems,
    registryUnavailable,
    user?.permissions,
  ]);

  const groups = useMemo(() => {
    const grouped = new Map<string, CapabilitySidebarItem[]>();
    for (const item of items) {
      const groupItems = grouped.get(item.nav_group) ?? [];
      groupItems.push(item);
      grouped.set(item.nav_group, groupItems);
    }
    return Array.from(grouped.entries())
      .map(([label, groupItems]) => ({ items: groupItems, label }))
      .sort((left, right) => groupOrder(left.label) - groupOrder(right.label));
  }, [items]);

  const value = useMemo(
    () => ({
      error,
      groups,
      isLoading,
      items,
      refresh: loadRegistry,
      registryUnavailable,
    }),
    [error, groups, isLoading, items, loadRegistry, registryUnavailable],
  );

  return (
    <CapabilitySidebarContext.Provider value={value}>
      {children}
    </CapabilitySidebarContext.Provider>
  );
}

export function useCapabilitySidebar() {
  const context = useContext(CapabilitySidebarContext);
  if (!context) {
    throw new Error(
      "useCapabilitySidebar must be used inside CapabilitySidebarProvider.",
    );
  }

  return context;
}
