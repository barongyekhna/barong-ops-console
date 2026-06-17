import { Database } from "lucide-react";
import type { Metadata } from "next";

import { CapabilityEmptyState } from "@/components/capability-empty-state";

export const metadata: Metadata = {
  title: "Logs",
};

export default function MemoryEventsPage() {
  return (
    <CapabilityEmptyState
      icon={Database}
      next_action_href="/operation-logs"
      next_action_label="Open logs"
      reason="This view has moved to Logs."
      required_execution_mode="View access is available."
      required_module_state="Logs must be available for this workspace."
      required_org_state="Active workspace access is required."
      required_permission="Log access granted by an owner."
      state="missing_feature"
      title="Use Logs for operation history"
      unlock_condition="Open Logs from the sidebar."
    />
  );
}
