import type { Metadata } from "next";

import { FoundationList } from "@/components/foundation-list";

export const metadata: Metadata = {
  title: "Memory Events",
};

export default function MemoryEventsPage() {
  return (
    <FoundationList
      emptyDescription="Foundation and demo memory events will appear here."
      emptyTitle="No memory events recorded."
      endpoint="/memory-events"
      fields={[
        { key: "memory_event_id", label: "Memory event ID" },
        { key: "event_type", label: "Type" },
        { key: "importance", label: "Importance" },
      ]}
      title="Memory events"
    />
  );
}
