import { Building2 } from "lucide-react";
import type { Metadata } from "next";

import { CapabilityEmptyState } from "@/components/capability-empty-state";

export const metadata: Metadata = {
  title: "Organizations",
};

export default function OrganizationsPage() {
  return (
    <CapabilityEmptyState
      icon={Building2}
      next_action_href="/users"
      next_action_label="Open users"
      reason="Organization management is available through workspace ownership and membership setup. A dedicated organization list is not available in this release."
      required_execution_mode="View access is available."
      required_module_state="Organizations must be enabled for this workspace."
      required_org_state="Active workspace access is required."
      required_permission="Organization access granted by an owner."
      state="missing_feature"
      title="Organization management is not available yet"
      unlock_condition="Use Users while organization management is completed."
    />
  );
}
