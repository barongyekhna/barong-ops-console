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
  dataSource = "Backend list API returned zero records.",
  title,
  description,
  icon: Icon = Inbox,
  requiredExecutionMode = "Read-only mode is sufficient.",
  requiredModuleState = "Module installed and visible.",
  requiredOrgState = "Active organization context is available.",
  requiredPermission = "Read permission for this capability.",
  unlockCondition = "Records will appear when the backend stores matching data.",
}: EmptyStateProps) {
  return (
    <CapabilityEmptyState
      icon={Icon}
      reason={`${description} Source: ${dataSource}`}
      required_execution_mode={requiredExecutionMode}
      required_module_state={requiredModuleState}
      required_org_state={requiredOrgState}
      required_permission={requiredPermission}
      state="allowed"
      title={title}
      unlock_condition={unlockCondition}
    />
  );
}
