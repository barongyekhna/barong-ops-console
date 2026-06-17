import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "System Issues",
};

export default function ErrorsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="No system issue records match the current view."
      emptyTitle="No system issues recorded."
      endpoint="/errors"
      fields={[
        { key: "error_id", label: "Issue ID" },
        { key: "error_code", label: "Code" },
        { key: "status", label: "Status" },
      ]}
      requiredPermission="operation_logs.read"
      title="System Issues"
    />
  );
}
