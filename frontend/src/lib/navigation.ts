import {
  Activity,
  Bot,
  Briefcase,
  Building2,
  Boxes,
  CircleAlert,
  ClipboardCheck,
  Database,
  FileText,
  GitBranch,
  Headphones,
  Images,
  LayoutDashboard,
  LockKeyhole,
  PackageSearch,
  Settings,
  ShieldCheck,
  Sparkles,
  UploadCloud,
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
        href: "/p-upload",
        icon: UploadCloud,
        label: "P系列自动化上传",
        module_key: "p.upload",
        required_permission: "p.upload.read",
        route_namespace: "/p-upload",
        status: "active",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/r-w/dashboard",
        icon: Database,
        label: "R-W 产品数据仓库",
        module_key: "r.warehouse",
        route_namespace: "/r-w",
        status: "active",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/r-a/live",
        icon: ClipboardCheck,
        label: "R-A 产品分析中心",
        module_key: "r.analysis",
        route_namespace: "/r-a",
        status: "active",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/f-enrichment",
        icon: GitBranch,
        label: "F 类目富化",
        module_key: "f.enrichment",
        required_permission: "f.enrichment.read",
        route_namespace: "/f-enrichment",
        status: "active",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/h-site-health",
        icon: Activity,
        label: "H 站点健康",
        module_key: "h.site_health",
        required_permission: "h.site_health.read",
        route_namespace: "/h-site-health",
        status: "active",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/b2b-wholesale",
        icon: Briefcase,
        label: "B2B 业务",
        module_key: "b2b.wholesale",
        required_permission: "b2b.wholesale.read",
        route_namespace: "/b2b-wholesale",
        status: "active",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/geo",
        icon: Sparkles,
        label: "GEO 内容引擎",
        module_key: "geo.content",
        required_permission: "geo.content.read",
        route_namespace: "/geo",
        status: "active",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/w-s",
        icon: Boxes,
        label: "W-S 物流网络中枢",
        module_key: "w.site_ops",
        required_permission: "w.site_ops.read",
        route_namespace: "/w-s",
        status: "active",
      },
      {
        category: "business",
        denied_behavior: "show_locked",
        href: "/cs/customer-service",
        icon: Headphones,
        label: "客服中心",
        module_key: "cs.customer_service",
        required_permission: "cs.customer_service.read",
        route_namespace: "/cs/customer-service",
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
        category: "core",
        denied_behavior: "hide_when_denied",
        href: "/vpn",
        icon: ShieldCheck,
        label: "VPN",
        module_key: "core.vpn",
        route_namespace: "/vpn",
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
        href: "/key-health",
        icon: ShieldCheck,
        label: "密钥检测",
        module_key: "admin.key_health",
        owner_only: true,
        required_permission: "modules.read",
        route_namespace: "/key-health",
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
