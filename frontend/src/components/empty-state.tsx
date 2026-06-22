import { Inbox, type LucideIcon } from "lucide-react";
import { CapabilityEmptyState } from "@/components/capability-empty-state";

type EmptyStateProps = {
  title: string;
  description: string;
  icon?: LucideIcon;
  dataSource?: string;
  requiredPermission?: string;
  requiredOrgState?: string;
  requiredModuleState?: string;
  requiredExecutionMode?: string;
  unlockCondition?: string;
};

export function EmptyState({
  dataSource,
  title,
  description,
  icon: Icon = Inbox,
  requiredExecutionMode = "可查看。",
  requiredModuleState = "功能区可用。",
  requiredOrgState = "组织状态正常。",
  requiredPermission = "当前账号可访问。",
  unlockCondition = "有记录后会显示在这里。",
}: EmptyStateProps) {
  void dataSource;

  return (
    <CapabilityEmptyState
      icon={Icon}
      next_action_label="刷新"
      reason={description}
      required_execution_mode={requiredExecutionMode}
      required_module_state={requiredModuleState}
      required_org_state={requiredOrgState}
      required_permission={requiredPermission}
      state="no_data"
      title={title}
      unlock_condition={unlockCondition}
    />
  );
}
