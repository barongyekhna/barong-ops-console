import {
  Building2,
  ClipboardCheck,
  FileText,
  LayoutDashboard,
  LockKeyhole,
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
    label: "Core",
    items: [
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
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
        owner_only: true,
        required_permission: "organizations.read",
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
    label: "Operations",
    items: [
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
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/approvals",
        icon: ClipboardCheck,
        label: "Approvals",
        module_key: "business.approvals",
        required_permission: "reviews.read",
        route_namespace: "/approvals",
        status: "enabled",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/jobs",
        icon: ClipboardCheck,
        label: "Jobs (Records)",
        module_key: "business.jobs",
        required_permission: "jobs.read",
        route_namespace: "/jobs",
        status: "enabled",
      },
    ],
  },
  {
    label: "System",
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
        denied_behavior: "show_locked",
        href: "/settings",
        icon: Settings,
        label: "Settings",
        module_key: "admin.settings",
        owner_only: true,
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

Object.assign(pageTitles, {
  "/agents": "Automation Directory",
  "/approvals": "Approvals",
  "/artifacts": "Records",
  "/dashboard": "Operations Hub",
  "/errors": "System Issues",
  "/memory-events": "Logs",
  "/modules": "Product Areas",
  "/operation-logs": "Logs",
  "/permissions": "Permissions",
  "/products": "Products",
  "/reviews": "Approvals",
  "/users": "Users",
  "/workflows": "Execution Workflows",
});
