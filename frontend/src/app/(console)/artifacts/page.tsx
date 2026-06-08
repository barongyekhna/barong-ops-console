import type { Metadata } from "next";

import { FoundationList } from "@/components/foundation-list";

export const metadata: Metadata = {
  title: "Artifacts",
};

export default function ArtifactsPage() {
  return (
    <FoundationList
      emptyDescription="Artifact metadata records will appear here."
      emptyTitle="No artifacts registered yet."
      endpoint="/artifacts"
      fields={[
        { key: "artifact_id", label: "Artifact ID" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
      ]}
      title="Artifacts"
    />
  );
}
