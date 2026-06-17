import { LockKeyhole } from "lucide-react";
import type { Metadata } from "next";

import { CapabilityEmptyState } from "@/components/capability-empty-state";

export const metadata: Metadata = {
  title: "Permissions",
};

export default function PermissionsPage() {
  return (
    <CapabilityEmptyState
      icon={LockKeyhole}
      next_action_href="/users"
      next_action_label="Open users"
      reason="Permissions are managed from each user profile so access changes stay tied to a person."
      required_execution_mode="View access is available."
      required_module_state="User access management must be available."
      required_org_state="Active workspace access is required."
      required_permission="Permission management access granted by an owner."
      state="no_data"
      title="Select a user to manage permissions"
      unlock_condition="Open Users and choose an account."
    />
  );
}
