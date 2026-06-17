import { Boxes } from "lucide-react";
import type { Metadata } from "next";

import { CapabilityEmptyState } from "@/components/capability-empty-state";

export const metadata: Metadata = {
  title: "Product Areas",
};

export default function ModulesPage() {
  return (
    <CapabilityEmptyState
      icon={Boxes}
      next_action_href="/dashboard"
      next_action_label="Open dashboard"
      reason="Product areas are managed by the platform and are not exposed as a workspace page."
      required_execution_mode="View access is available."
      required_module_state="Product areas are configured by the platform."
      required_org_state="Active workspace access is required."
      required_permission="Owner access."
      state="missing_feature"
      title="Product areas are managed for you"
      unlock_condition="Use the product navigation in the sidebar."
    />
  );
}
