"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function ArtifactsPage() {
  return (
    <ProductResourceConsole
      actions={[
        {
          buildPayload: (values, record) => ({
            ...values,
            artifact_id: record.artifact_id,
            status: "pending_demo",
          }),
          description: "Create a review request for the selected artifact.",
          endpoint: "/reviews",
          fields: [
            {
              key: "review_id",
              label: "Review ID",
              placeholder: "demo.artifact.review",
              required: true,
            },
            {
              defaultValue: "artifact_review",
              key: "review_type",
              label: "Review type",
              required: true,
            },
            {
              defaultValue: "low",
              key: "risk_level",
              label: "Risk level",
              required: true,
            },
          ],
          key: "artifact-review",
          label: "Request review",
          submitLabel: "Request review",
          title: "Artifact review",
        },
      ]}
      description="Inspect and route artifact metadata into review queues."
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
