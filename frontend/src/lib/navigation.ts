import {
  Building2,
  ClipboardCheck,
  FileText,
  LockKeyhole,
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
