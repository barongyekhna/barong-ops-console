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

export type NavigationItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  module_key: string;
  required_permission?: string;
  category: PermissionCategory;
  denied_behavior: PermissionDeniedBehavior;
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
        category: "business",
        denied_behavior: "show_locked",
        href: "/dashboard",
        label: "Dashboard",
        icon: LayoutDashboard,
        module_key: "dashboard",
        required_permission: "jobs.read",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/foundation-demo",
        label: "Foundation Demo",
        icon: Activity,
        module_key: "foundation_demo",
        required_permission: "jobs.create",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/n8n-test",
        label: "n8n Test Bridge",
        icon: Workflow,
        module_key: "n8n_test",
        required_permission: "jobs.create",
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
        module_key: "products",
        required_permission: "products.read",
      },
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/modules",
        icon: Boxes,
        label: "Modules",
        module_key: "modules",
        required_permission: "modules.read",
      },
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/agents",
        icon: Bot,
        label: "Agents",
        module_key: "agents",
        required_permission: "modules.read",
      },
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/workflows",
        icon: Workflow,
        label: "Workflows",
        module_key: "workflows",
        required_permission: "modules.read",
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
        module_key: "jobs",
        required_permission: "jobs.read",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/artifacts",
        icon: Archive,
        label: "Artifacts",
        module_key: "artifacts",
        required_permission: "artifacts.read",
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
        module_key: "reviews",
        required_permission: "reviews.read",
      },
      {
        category: "system",
        denied_behavior: "hide_when_denied",
        href: "/errors",
        icon: CircleAlert,
        label: "Errors",
        module_key: "errors",
        required_permission: "operation_logs.read",
      },
      {
        category: "system",
        denied_behavior: "hide_when_denied",
        href: "/memory-events",
        icon: Database,
        label: "Memory Events",
        module_key: "memory_events",
        required_permission: "operation_logs.read",
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
        module_key: "users",
        owner_only: true,
        required_permission: "users.manage",
      },
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/settings",
        icon: Settings,
        label: "Settings",
        module_key: "settings",
        required_permission: "settings.read",
      },
    ],
  },
];

export const navigationItems = navigationGroups.flatMap(
  (group) => group.items,
);

export const pageTitles = Object.fromEntries(
  navigationGroups.flatMap((group) =>
    group.items.map((item) => [item.href, item.label]),
  ),
) as Record<string, string>;
