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
    label: "Core System",
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
    ],
  },
  {
    label: "Operations",
    items: [
      {
        category: "system",
        denied_behavior: "hide_when_denied",
        href: "/operation-logs",
        icon: Database,
        label: "Operation Logs",
        module_key: "system.operation_logs",
        required_permission: "operation_logs.read",
        route_namespace: "/operation-logs",
        status: "sealed",
      },
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
    ],
  },
  {
    label: "Registry",
    items: [
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
    icon: LockKeyhole,
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
