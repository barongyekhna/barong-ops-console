"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { NoPermissionNotice } from "@/components/no-permission-notice";
import { navigationItems } from "@/lib/navigation";
import { getRoutePermissionDecision } from "@/lib/permissions";

export function PermissionRouteGuard({
  children,
}: {
  children: ReactNode;
}) {
  const pathname = usePathname();
  const { user } = useAuth();
  const decision = getRoutePermissionDecision(
    user?.permissions,
    pathname,
    navigationItems,
  );

  if (decision.isProtected && !decision.canAccess) {
    return <NoPermissionNotice />;
  }

  return children;
}
