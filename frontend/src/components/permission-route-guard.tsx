"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { useModuleAccess } from "@/components/module-access-provider";
import {
  ModuleUnavailableNotice,
  NoPermissionNotice,
} from "@/components/no-permission-notice";
import { navigationModuleRecords } from "@/lib/navigation";
import { getModuleRouteDecision } from "@/lib/module-registry";

export function PermissionRouteGuard({
  children,
}: {
  children: ReactNode;
}) {
  const pathname = usePathname();
  const { user } = useAuth();
  const { items, moduleAccessUnknown } = useModuleAccess();
  const decision = getModuleRouteDecision(
    user?.permissions,
    pathname,
    navigationModuleRecords,
    items,
    { moduleAccessUnknown },
  );

  if (decision.isProtected && !decision.canEnter) {
    if (decision.noticeType === "module_unavailable") {
      return <ModuleUnavailableNotice />;
    }

    return <NoPermissionNotice />;
  }

  return children;
}
