import type { Metadata } from "next";

import { FoundationList } from "@/components/foundation-list";

export const metadata: Metadata = {
  title: "Agents",
};

export default function AgentsPage() {
  return (
    <FoundationList
      emptyDescription="Foundation and demo agent records will appear here."
      emptyTitle="No agents registered yet."
      endpoint="/agents"
      fields={[
        { key: "agent_key", label: "Agent key" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
      ]}
      title="Agent registry"
    />
  );
}
