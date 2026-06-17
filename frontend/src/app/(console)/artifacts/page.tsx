import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Records",
};

export default function ArtifactsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="Workspace records will appear here when they are available."
      emptyTitle="No records yet."
      endpoint="/artifacts"
      fields={[
        { key: "artifact_id", label: "Record ID" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
      ]}
      requiredPermission="artifacts.read"
      title="Records"
    />
  );
}
