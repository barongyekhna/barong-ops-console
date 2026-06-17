import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Execution Workflows",
};

export default function WorkflowsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="Execution workflow records will appear here when they are available."
      emptyTitle="No execution workflows yet."
      endpoint="/workflows"
      fields={[
        { key: "workflow_key", label: "Workflow ID" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
      ]}
      requiredPermission="modules.read"
      title="Execution Workflows"
    />
  );
}
