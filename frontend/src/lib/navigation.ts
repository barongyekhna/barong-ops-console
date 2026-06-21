import {
  Archive,
  Bot,
  Building2,
  Boxes,
  CircleAlert,
  ClipboardCheck,
  Database,
  FileText,
  LayoutDashboard,
  LockKeyhole,
  Package,
  Settings,
  UserRoundCog,
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
    label: "Users & Organizations",
    items: [
      {
        category: "admin",
        denied_behavior: "show_locked",
        href: "/users",
        icon: UserRoundCog,
        label: "Users",
        module_key: "admin.users",
        owner_only: true,
        required_permission: "users.manage",
        route_namespace: "/users",
        status: "sealed",
      },
      {
        category: "admin",
        denied_behavior: "show_locked",
        href: "/organizations",
        icon: Building2,
        label: "Organizations",
        module_key: "admin.organizations",
        route_namespace: "/organizations",
        status: "enabled",
      },
      {
        category: "admin",
        denied_behavior: "show_locked",
        href: "/permissions",
        icon: LockKeyhole,
        label: "Permissions",
        module_key: "admin.permissions",
        owner_only: true,
        required_permission: "permissions.read",
        route_namespace: "/permissions",
        status: "sealed",
      },
    ],
  },
  {
    label: "Business Modules",
    items: [
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/approvals",
        icon: ClipboardCheck,
        label: "审批",
        module_key: "business.approvals",
        required_permission: "reviews.read",
        route_namespace: "/approvals",
        status: "enabled",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/reviews",
        icon: ClipboardCheck,
        label: "审批审计",
        module_key: "business.reviews",
        required_permission: "reviews.read",
        route_namespace: "/reviews",
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
    label: "System Modules",
    items: [
      {
        category: "core",
        denied_behavior: "show_locked",
        href: "/dashboard",
        icon: LayoutDashboard,
        label: "Dashboard",
        module_key: "core.dashboard",
        route_namespace: "/dashboard",
        status: "sealed",
      },
      {
        category: "admin",
        denied_behavior: "show_locked",
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
        denied_behavior: "show_locked",
        href: "/settings",
        icon: Settings,
        label: "Settings",
        module_key: "admin.settings",
        required_permission: "settings.read",
        route_namespace: "/settings",
        status: "planned",
      },
      {
        category: "system",
        denied_behavior: "show_locked",
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
        denied_behavior: "show_locked",
        href: "/memory-events",
        icon: Database,
        label: "Memory Events",
        module_key: "system.memory_events",
        required_permission: "operation_logs.read",
        route_namespace: "/memory-events",
        status: "enabled",
      },
      {
        category: "system",
        denied_behavior: "show_locked",
        href: "/operation-logs",
        icon: FileText,
        label: "Logs",
        module_key: "system.operation_logs",
        required_permission: "operation_logs.read",
        route_namespace: "/operation-logs",
        status: "sealed",
      },
    ],
  },
  {
    label: "Extensions",
    items: [
      {
        category: "admin",
        denied_behavior: "show_locked",
        href: "/agents",
        icon: Bot,
        label: "Agents",
        module_key: "admin.agents",
        required_permission: "modules.read",
        route_namespace: "/agents",
        status: "sealed",
      },
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
    ],
  },
];

export const navigationItems = navigationGroups.flatMap(
  (group) => group.items,
);

export const embeddedNavigationModules: ModuleAwareNavigationRecord[] = [
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
