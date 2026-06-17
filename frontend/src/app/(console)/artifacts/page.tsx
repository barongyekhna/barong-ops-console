import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Artifacts",
};

export default function ArtifactsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="Artifact metadata records will appear here."
      emptyTitle="No artifacts registered yet."
      endpoint="/artifacts"
      fields={[
        { key: "artifact_id", label: "Artifact ID" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
      ]}
      requiredPermission="artifacts.read"
      title="Artifacts"
    />
  );
}
