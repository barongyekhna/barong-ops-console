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
      required_execution_mode="Actions do not bypass account access."
      required_module_state="This product area must be available."
      required_org_state="Active organization access is required."
      required_permission="Access granted by an owner."
      state="no_permission"
      title={title}
      unlock_condition="Ask an owner to grant access."
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
      required_execution_mode="Actions must be enabled before use."
      required_module_state="This product area must be available."
      required_org_state="Active organization access is required."
      required_permission="Access granted by an owner."
      state="missing_feature"
      title={title}
      unlock_condition="Ask an owner to finish setup."
    />
  );
}
