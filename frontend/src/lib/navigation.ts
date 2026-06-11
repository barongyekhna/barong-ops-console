import {
  Activity,
  Archive,
  Bot,
  Boxes,
  CircleAlert,
  ClipboardCheck,
  Database,
  LayoutDashboard,
  Package,
  Settings,
  Sparkles,
  UserRoundCog,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import type {
  PermissionCategory,
  PermissionDeniedBehavior,
} from "@/lib/permissions";
import type {
  ModuleAwareNavigationRecord,
  ModuleStatus,
} from "@/lib/module-registry";

export type NavigationItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  module_key: string;
  route_namespace: string;
  required_permission?: string;
  category: PermissionCategory;
  denied_behavior: PermissionDeniedBehavior;
  status: ModuleStatus;
  owner_only?: boolean;
};

export type NavigationGroup = {
  label: string;
  items: NavigationItem[];
};

export const navigationGroups: NavigationGroup[] = [
  {
    label: "Overview",
    items: [
      {
        category: "core",
        denied_behavior: "hide_when_denied",
        href: "/dashboard",
        label: "Dashboard",
        icon: LayoutDashboard,
        module_key: "core.dashboard",
        route_namespace: "/dashboard",
        status: "sealed",
      },
      {
        category: "experimental",
        denied_behavior: "hide_when_denied",
        href: "/foundation-demo",
        label: "Foundation Demo",
        icon: Activity,
        module_key: "experimental.foundation_demo",
        route_namespace: "/foundation-demo",
        required_permission: "jobs.create",
        status: "enabled",
      },
      {
        category: "integration",
        denied_behavior: "hide_when_denied",
        href: "/n8n-test",
        label: "n8n Test Bridge",
        icon: Workflow,
        module_key: "integration.n8n_test_bridge",
        route_namespace: "/n8n-test",
        required_permission: "jobs.create",
        status: "adapter_pending",
      },
    ],
  },
  {
    label: "Registry",
    items: [
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/products",
        icon: Package,
        label: "Products",
        module_key: "business.products",
        required_permission: "products.read",
        route_namespace: "/products",
        status: "planned",
      },
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/modules",
        icon: Boxes,
        label: "Modules",
        module_key: "admin.modules",
        required_permission: "modules.read",
        route_namespace: "/modules",
        status: "sealed",
      },
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/agents",
        icon: Bot,
        label: "Agents",
        module_key: "admin.agents",
        required_permission: "modules.read",
        route_namespace: "/agents",
        status: "sealed",
      },
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/workflows",
        icon: Workflow,
        label: "Workflows",
        module_key: "admin.workflows",
        required_permission: "modules.read",
        route_namespace: "/workflows",
        status: "sealed",
      },
    ],
  },
  {
    label: "Operations",
    items: [
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/jobs",
        icon: Sparkles,
        label: "Jobs",
        module_key: "business.jobs",
        required_permission: "jobs.read",
        route_namespace: "/jobs",
        status: "enabled",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/artifacts",
        icon: Archive,
        label: "Artifacts",
        module_key: "business.artifacts",
        required_permission: "artifacts.read",
        route_namespace: "/artifacts",
        status: "enabled",
      },
    ],
  },
  {
    label: "Governance",
    items: [
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/reviews",
        icon: ClipboardCheck,
        label: "Reviews",
        module_key: "business.reviews",
        required_permission: "reviews.read",
        route_namespace: "/reviews",
        status: "enabled",
      },
      {
        category: "system",
        denied_behavior: "hide_when_denied",
        href: "/errors",
        icon: CircleAlert,
        label: "Errors",
        module_key: "system.errors",
        required_permission: "operation_logs.read",
        route_namespace: "/errors",
        status: "enabled",
      },
      {
        category: "system",
        denied_behavior: "hide_when_denied",
        href: "/memory-events",
        icon: Database,
        label: "Memory Events",
        module_key: "system.memory_events",
        required_permission: "operation_logs.read",
        route_namespace: "/memory-events",
        status: "enabled",
      },
    ],
  },
  {
    label: "System",
    items: [
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/users",
        icon: UserRoundCog,
        label: "User Management",
        module_key: "admin.users",
        owner_only: true,
        required_permission: "users.manage",
        route_namespace: "/users",
        status: "sealed",
      },
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/settings",
        icon: Settings,
        label: "Settings",
        module_key: "admin.settings",
        required_permission: "settings.read",
        route_namespace: "/settings",
        status: "planned",
      },
    ],
  },
];

export const navigationItems = navigationGroups.flatMap(
  (group) => group.items,
);

export const embeddedNavigationModules: ModuleAwareNavigationRecord[] = [
  {
    category: "admin",
    denied_behavior: "hide_when_denied",
    embedded: true,
    href: "/users",
    label: "Permission Management",
    module_key: "admin.permissions",
    owner_only: true,
    required_permission: "permissions.read",
    route_namespace: "/users",
    status: "sealed",
  },
];

export const navigationModuleRecords: ModuleAwareNavigationRecord[] = [
  ...navigationItems,
  ...embeddedNavigationModules,
];

export const pageTitles = Object.fromEntries(
  navigationGroups.flatMap((group) =>
    group.items.map((item) => [item.href, item.label]),
  ),
) as Record<string, string>;
