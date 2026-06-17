import { Settings } from "lucide-react";
import type { Metadata } from "next";

import { CapabilityEmptyState } from "@/components/capability-empty-state";

export const metadata: Metadata = {
  title: "Settings",
};

export default function SettingsPage() {
  return (
    <CapabilityEmptyState
      icon={Settings}
      next_action_href="/dashboard"
      next_action_label="Open dashboard"
      reason="Workspace settings are not available in this release."
      required_execution_mode="View access is available."
      required_module_state="Settings must be enabled for this workspace."
      required_org_state="Active workspace access is required."
      required_permission="Settings access granted by an owner."
      state="missing_feature"
      title="Settings are not available yet"
      unlock_condition="Use the dashboard while settings are completed."
    />
  );
}
