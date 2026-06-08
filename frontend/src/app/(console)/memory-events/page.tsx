import { Database } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = {
  title: "Memory Events",
};

export default function MemoryEventsPage() {
  return (
    <EmptyState
      description="Long-lived context events will appear here."
      icon={Database}
      title="No memory events recorded."
    />
  );
}
