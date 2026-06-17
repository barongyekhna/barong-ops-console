import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Errors",
};

export default function ErrorsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="No system error records match the current backend result set."
      emptyTitle="No errors recorded."
      endpoint="/errors"
      fields={[
        { key: "error_id", label: "Error ID" },
        { key: "error_code", label: "Code" },
        { key: "status", label: "Status" },
      ]}
      requiredPermission="operation_logs.read"
      title="System errors"
    />
  );
}
