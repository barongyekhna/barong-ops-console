import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Workflows",
};

export default function WorkflowsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="Workflow metadata records will appear here."
      emptyTitle="No workflows registered yet."
      endpoint="/workflows"
      fields={[
        { key: "workflow_key", label: "Workflow key" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
      ]}
      requiredPermission="modules.read"
      title="Workflow registry"
    />
  );
}
