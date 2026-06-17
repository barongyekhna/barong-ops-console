import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Operation Logs",
};

export default function OperationLogsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="No operation log records match the current backend result set."
      emptyTitle="No operation logs recorded."
      endpoint="/operation-logs"
      fields={[
        { key: "operation_id", label: "Operation ID" },
        { key: "action", label: "Action" },
        { key: "status", label: "Status" },
        { key: "module_key", label: "Module" },
      ]}
      requiredPermission="operation_logs.read"
      title="Operation logs"
    />
  );
}
