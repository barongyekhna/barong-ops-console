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
      required_execution_mode="操作必须符合账号权限。"
      required_module_state="功能区需要可用。"
      required_org_state="需要组织访问权限。"
      required_permission="需要所有者开通访问权限。"
      state="no_permission"
      title={title}
      unlock_condition="请联系所有者开通访问权限。"
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
      required_execution_mode="操作能力需要先启用。"
      required_module_state="功能区需要可用。"
      required_org_state="需要组织访问权限。"
      required_permission="需要所有者开通访问权限。"
      state="missing_feature"
      title={title}
      unlock_condition="请联系所有者完成配置。"
    />
  );
}
