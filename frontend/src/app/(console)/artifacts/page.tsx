import { Archive } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = {
  title: "Artifacts",
};

export default function ArtifactsPage() {
  return (
    <EmptyState
      description="Registered artifacts will appear here."
      icon={Archive}
      title="No artifacts registered yet."
    />
  );
}
