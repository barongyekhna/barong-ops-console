import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Automation Directory",
};

export default function AgentsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="No automation records match the current view."
      emptyTitle="No automation records yet."
      endpoint="/agents"
      fields={[
        { key: "agent_key", label: "Automation ID" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
      ]}
      requiredPermission="modules.read"
      title="Automation Directory"
    />
  );
}
