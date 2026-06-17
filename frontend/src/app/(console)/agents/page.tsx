import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Agents",
};

export default function AgentsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="No agent records match the current backend result set."
      emptyTitle="No agents registered yet."
      endpoint="/agents"
      fields={[
        { key: "agent_key", label: "Agent key" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
      ]}
      requiredPermission="modules.read"
      title="Agent registry"
    />
  );
}
