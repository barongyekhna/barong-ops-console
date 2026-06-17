import type { Metadata } from "next";

import { CapabilityEmptyState } from "@/components/capability-empty-state";
import { N8nTestPanel } from "@/components/n8n-test-panel";

export const metadata: Metadata = {
  title: "Internal Diagnostics",
};

export default function N8nTestPage() {
  const diagnosticsEnabled =
    process.env.NODE_ENV !== "production" &&
    process.env.NEXT_PUBLIC_ENABLE_INTERNAL_DIAGNOSTICS === "true";

  if (!diagnosticsEnabled) {
    return (
      <CapabilityEmptyState
        reason="This diagnostic route is hidden from production product navigation."
        required_execution_mode="No production execution mode is allowed for this diagnostic route."
        required_module_state="Diagnostic module must remain outside the production capability graph."
        required_org_state="Not available through organization module visibility."
        required_permission="Internal diagnostics flag, not product permission."
        state="hidden"
        title="Diagnostic route hidden"
        unlock_condition="Enable the internal diagnostics flag in a non-production build."
      />
    );
  }

  return (
    <div className="page-stack">
      <div className="page-heading">
        <span className="section-index">INT</span>
        <div>
          <h2>Internal diagnostics</h2>
          <p>Read diagnostic bridge status without exposing product execution controls.</p>
        </div>
      </div>
      <N8nTestPanel />
    </div>
  );
}
