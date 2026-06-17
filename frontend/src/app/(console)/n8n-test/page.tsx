import type { Metadata } from "next";

import { CapabilityEmptyState } from "@/components/capability-empty-state";

export const metadata: Metadata = {
  title: "Hidden Capability",
};

export default function N8nTestPage() {
  return (
    <CapabilityEmptyState
      reason="This internal route is excluded from the production capability graph."
      required_execution_mode="No production execution mode is allowed for this route."
      required_module_state="A durable product adapter must replace the internal route before exposure."
      required_org_state="Not available through organization module visibility."
      required_permission="No product permission unlocks this route."
      state="hidden"
      title="Capability hidden"
      unlock_condition="Install a production capability with a durable backend binding."
    />
  );
}
