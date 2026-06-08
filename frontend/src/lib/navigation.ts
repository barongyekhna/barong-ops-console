import {
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
  Workflow,
  type LucideIcon,
} from "lucide-react";

export type NavigationItem = {
  href: string;
  label: string;
  icon: LucideIcon;
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
        href: "/dashboard",
        label: "Dashboard",
        icon: LayoutDashboard,
      },
    ],
  },
  {
    label: "Registry",
    items: [
      { href: "/products", label: "Products", icon: Package },
      { href: "/modules", label: "Modules", icon: Boxes },
      { href: "/agents", label: "Agents", icon: Bot },
      { href: "/workflows", label: "Workflows", icon: Workflow },
    ],
  },
  {
    label: "Operations",
    items: [
      { href: "/jobs", label: "Jobs", icon: Sparkles },
      { href: "/artifacts", label: "Artifacts", icon: Archive },
    ],
  },
  {
    label: "Governance",
    items: [
      { href: "/reviews", label: "Reviews", icon: ClipboardCheck },
      { href: "/errors", label: "Errors", icon: CircleAlert },
      { href: "/memory-events", label: "Memory Events", icon: Database },
    ],
  },
  {
    label: "System",
    items: [{ href: "/settings", label: "Settings", icon: Settings }],
  },
];

export const pageTitles = Object.fromEntries(
  navigationGroups.flatMap((group) =>
    group.items.map((item) => [item.href, item.label]),
  ),
) as Record<string, string>;
