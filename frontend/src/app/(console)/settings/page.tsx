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
      reason="The settings route is not backed by a production settings API capability."
      required_execution_mode="Read-only admin backend binding."
      required_module_state="admin.settings must be enabled with a durable settings API."
      required_org_state="Active organization context must allow admin settings."
      required_permission="settings.read"
      state="hidden"
      title="Settings capability is not installed"
      unlock_condition="Add a durable settings backend contract before exposing this route."
    />
  );
}
