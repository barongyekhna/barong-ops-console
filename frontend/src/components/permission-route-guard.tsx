"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { CapabilityEmptyStateEngine } from "@/components/capability-empty-state";
import { useFrontendCapabilityState } from "@/components/capability-state-provider";
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
  const { getCapabilityForPath, permissionSnapshot } =
    useFrontendCapabilityState();
  const { items, moduleAccessUnknown } = useModuleAccess();
  const capability = getCapabilityForPath(pathname);
  const isOwner = permissionSnapshot.is_owner_full_access === true;

  if (isOwner) {
    return children;
  }

  if (capability && !capability.can_enter) {
    return (
      <CapabilityEmptyStateEngine
        reason={capability.reason}
        required_execution_mode={capability.required_execution_mode}
        required_module_state={capability.required_module_state}
        required_org_state={capability.required_org_state}
        required_permission={capability.required_permission}
        state={capability.state}
        title={`${capability.label} is not available`}
        unlock_condition={capability.unlock_condition}
      />
    );
  }

  const decision = getModuleRouteDecision(
    null,
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
