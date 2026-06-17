import { Package } from "lucide-react";
import type { Metadata } from "next";

import { CapabilityEmptyState } from "@/components/capability-empty-state";

export const metadata: Metadata = {
  title: "Products",
};

export default function ProductsPage() {
  return (
    <CapabilityEmptyState
      icon={Package}
      next_action_href="/dashboard"
      next_action_label="Open dashboard"
      reason="Products are not available in this workspace."
      required_execution_mode="Actions must be enabled before use."
      required_module_state="Products must be enabled for this workspace."
      required_org_state="Active workspace access is required."
      required_permission="Product access granted by an owner."
      state="missing_feature"
      title="Products are not available yet"
      unlock_condition="Use the dashboard while products are completed."
    />
  );
}
