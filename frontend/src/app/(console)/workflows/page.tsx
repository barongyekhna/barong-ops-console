import type { Metadata } from "next";

import { FoundationList } from "@/components/foundation-list";

export const metadata: Metadata = {
  title: "Workflows",
};

export default function WorkflowsPage() {
  return (
    <FoundationList
      emptyDescription="Workflow metadata records will appear here."
      emptyTitle="No workflows registered yet."
      endpoint="/workflows"
      fields={[
        { key: "workflow_key", label: "Workflow key" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
      ]}
      title="Workflow registry"
    />
  );
}
