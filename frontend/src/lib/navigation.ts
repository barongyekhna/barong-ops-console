import {
  Bot,
  Building2,
  Boxes,
  CircleAlert,
  ClipboardCheck,
  Database,
  FileText,
  Images,
  LayoutDashboard,
  LockKeyhole,
  PackageSearch,
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
    label: "账号与组织",
    items: [
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/users",
        icon: UserRoundCog,
        label: "用户管理",
        module_key: "admin.users",
        route_namespace: "/users",
        status: "sealed",
      },
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/organizations",
        icon: Building2,
        label: "组织管理",
        module_key: "admin.organizations",
        route_namespace: "/organizations",
        status: "enabled",
      },
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/permissions",
        icon: LockKeyhole,
        label: "权限管理",
        module_key: "admin.permissions",
        required_permission: "permissions.read",
        route_namespace: "/permissions",
        status: "sealed",
      },
    ],
  },
  {
    label: "业务处理",
    items: [
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/r-commerce",
        icon: PackageSearch,
        label: "R系列自动化选品系统",
        module_key: "r.commerce",
        required_permission: "r.commerce.read",
        route_namespace: "/r-commerce",
        status: "active",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/products",
        icon: PackageSearch,
        label: "产品知识库",
        module_key: "k.product_knowledge",
        required_permission: "products.read",
        route_namespace: "/products",
        status: "active",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/image-system",
        icon: Images,
        label: "I系列图片系统",
        module_key: "i.image_system",
        required_permission: "i.image_system.read",
        route_namespace: "/image-system",
        status: "active",
      },
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
    ],
  },
  {
    label: "系统管理",
    items: [
      {
        category: "core",
        denied_behavior: "hide_when_denied",
        href: "/dashboard",
        icon: LayoutDashboard,
        label: "控制台",
        module_key: "core.dashboard",
        route_namespace: "/dashboard",
        status: "sealed",
      },
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/module-control",
        icon: Boxes,
        label: "模块控制",
        module_key: "admin.modules",
        owner_only: true,
        required_permission: "modules.read",
        route_namespace: "/module-control",
        status: "sealed",
      },
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/api-key-management",
        icon: LockKeyhole,
        label: "API密钥管理",
        module_key: "admin.key_management",
        owner_only: true,
        required_permission: "modules.read",
        route_namespace: "/api-key-management",
        status: "sealed",
      },
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/settings",
        icon: Settings,
        label: "设置",
        module_key: "admin.settings",
        required_permission: "settings.read",
        route_namespace: "/settings",
        status: "planned",
      },
      {
        category: "system",
        denied_behavior: "hide_when_denied",
        href: "/errors",
        icon: CircleAlert,
        label: "异常记录",
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
        label: "运行记录",
        module_key: "system.memory_events",
        required_permission: "operation_logs.read",
        route_namespace: "/memory-events",
        status: "enabled",
      },
      {
        category: "system",
        denied_behavior: "hide_when_denied",
        href: "/operation-logs",
        icon: FileText,
        label: "操作记录",
        module_key: "system.operation_logs",
        required_permission: "operation_logs.read",
        route_namespace: "/operation-logs",
        status: "sealed",
      },
    ],
  },
  {
    label: "扩展能力",
    items: [
      {
        category: "admin",
        denied_behavior: "hide_when_denied",
        href: "/agents",
        icon: Bot,
        label: "自动化助手",
        module_key: "admin.agents",
        required_permission: "modules.read",
        route_namespace: "/agents",
        status: "sealed",
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
