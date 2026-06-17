import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Memory Audit Events",
};

export default function MemoryEventsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="No audit memory records match the current backend result set."
      emptyTitle="No memory audit events recorded."
      endpoint="/memory-events"
      fields={[
        { key: "memory_event_id", label: "Memory event ID" },
        { key: "event_type", label: "Type" },
        { key: "importance", label: "Importance" },
      ]}
      requiredPermission="operation_logs.read"
      title="Memory audit events"
    />
  );
}
