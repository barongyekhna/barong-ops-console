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
  dataSource = "No records are available yet.",
  title,
  description,
  icon: Icon = Inbox,
  requiredExecutionMode = "View access is available.",
  requiredModuleState = "Product area is available.",
  requiredOrgState = "Active organization context is available.",
  requiredPermission = "View permission for this area.",
  unlockCondition = "Records will appear when activity starts.",
}: EmptyStateProps) {
  return (
    <CapabilityEmptyState
      icon={Icon}
      next_action_label="Refresh"
      reason={`${description} ${dataSource}`}
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
