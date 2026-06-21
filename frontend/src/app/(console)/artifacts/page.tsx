"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function ArtifactsPage() {
  return (
    <ProductResourceConsole
      description="Inspect artifact metadata and storage references."
      detailEndpoint={(record) => `/artifacts/${record.artifact_id}`}
      detailFields={[
        { key: "artifact_id", label: "Artifact" },
        { key: "module_key", label: "Module" },
        { key: "artifact_type", label: "Type" },
        { key: "name", label: "Name" },
        { key: "storage_provider", label: "Storage" },
        { key: "storage_ref", label: "Reference" },
        { key: "status", label: "Status" },
        { key: "metadata", label: "Metadata" },
      ]}
      emptyDescription="Artifact metadata appears here when it is available."
      emptyTitle="No artifacts yet."
      endpoint="/artifacts?limit=50&offset=0"
      eyebrow="Business"
      fields={[
        { key: "artifact_id", label: "Artifact" },
        { key: "artifact_type", label: "Type" },
        { key: "status", label: "Status" },
      ]}
      idKey="artifact_id"
      requiredPermission="artifacts.read"
      title="Artifacts"
    />
  );
}
