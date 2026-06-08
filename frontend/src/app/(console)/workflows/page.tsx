import { Workflow } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = {
  title: "Workflows",
};

export default function WorkflowsPage() {
  return (
    <EmptyState
      description="Registered workflows will appear here."
      icon={Workflow}
      title="No workflows registered yet."
    />
  );
}
