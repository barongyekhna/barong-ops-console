import { Sparkles } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = {
  title: "Jobs",
};

export default function JobsPage() {
  return (
    <EmptyState
      description="Job records will appear here."
      icon={Sparkles}
      title="No jobs recorded yet."
    />
  );
}
