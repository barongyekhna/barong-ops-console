import { CircleSlash2, LockKeyhole } from "lucide-react";
import { CapabilityEmptyState } from "@/components/capability-empty-state";
import {
  MODULE_NO_PERMISSION_DESCRIPTION,
  MODULE_NO_PERMISSION_TITLE,
  MODULE_UNAVAILABLE_DESCRIPTION,
  MODULE_UNAVAILABLE_TITLE,
} from "@/lib/module-notices";

type NoPermissionNoticeProps = {
  title?: string;
  description?: string;
};

export function NoPermissionNotice({
  title = MODULE_NO_PERMISSION_TITLE,
  description = MODULE_NO_PERMISSION_DESCRIPTION,
}: NoPermissionNoticeProps) {
  return (
    <CapabilityEmptyState
      icon={LockKeyhole}
      reason={description}
      required_execution_mode="No execution mode grants permission bypass."
      required_module_state="Module must be visible and permission-allowed."
      required_org_state="Active organization context must include this module."
      required_permission="See the module permission manifest."
      state="forbidden"
      title={title}
      unlock_condition="Ask an owner to grant the required permission in C05/C06."
    />
  );
}

export function ModuleUnavailableNotice({
  title = MODULE_UNAVAILABLE_TITLE,
  description = MODULE_UNAVAILABLE_DESCRIPTION,
}: NoPermissionNoticeProps) {
  return (
    <CapabilityEmptyState
      icon={CircleSlash2}
      reason={description}
      required_execution_mode="Execution mode must be connected and non-mock."
      required_module_state="Module status must be enabled or sealed."
      required_org_state="Active organization context must expose this module."
      required_permission="See the module permission manifest."
      state="no_execution"
      title={title}
      unlock_condition="Enable the module, adapter, and execution provider before exposing this route."
    />
  );
}
