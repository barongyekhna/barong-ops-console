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
      create={{
        description: "Register artifact metadata against an existing job and module.",
        endpoint: "/artifacts",
        fields: [
          {
            key: "artifact_id",
            label: "Artifact ID",
            placeholder: "demo.artifact",
            required: true,
          },
          {
            key: "job_id",
            label: "Job ID",
            required: true,
          },
          {
            defaultValue: "business.products",
            key: "module_key",
            label: "Module key",
            required: true,
          },
          {
            defaultValue: "metadata",
            key: "artifact_type",
            label: "Artifact type",
            required: true,
          },
          {
            key: "name",
            label: "Name",
            required: true,
          },
          {
            defaultValue: "metadata_only",
            key: "storage_provider",
            label: "Storage provider",
            options: [
              { label: "Metadata only", value: "metadata_only" },
              { label: "Foundation metadata", value: "foundation_metadata" },
              { label: "Demo metadata", value: "demo_metadata" },
            ],
            required: true,
            type: "select",
          },
          {
            defaultValue: "foundation://metadata-only",
            key: "storage_ref",
            label: "Storage reference",
            required: true,
          },
          {
            defaultValue: "registered_demo",
            key: "status",
            label: "Status",
            options: [
              { label: "Registered demo", value: "registered_demo" },
              { label: "Draft demo", value: "draft_demo" },
            ],
            required: true,
            type: "select",
          },
          {
            defaultValue: "{}",
            key: "metadata",
            label: "Metadata",
            type: "json",
          },
        ],
        submitLabel: "Register artifact",
        title: "Register artifact",
      }}
      description="Register, inspect, and route artifact metadata into review workflows."
      detailEndpoint={(record) => `/artifacts/${record.artifact_id}`}
      detailFields={[
        { key: "artifact_id", label: "Artifact" },
        { key: "job_id", label: "Job" },
        { key: "module_key", label: "Module" },
        { key: "artifact_type", label: "Type" },
        { key: "name", label: "Name" },
        { key: "storage_provider", label: "Storage" },
        { key: "storage_ref", label: "Reference" },
        { key: "status", label: "Status" },
        { key: "metadata", label: "Metadata" },
      ]}
      emptyDescription="Register an artifact after a job exists."
      emptyTitle="No artifacts yet."
      endpoint="/artifacts?limit=50&offset=0"
      eyebrow="Business"
      fields={[
        { key: "artifact_id", label: "Artifact" },
        { key: "job_id", label: "Job" },
        { key: "artifact_type", label: "Type" },
        { key: "status", label: "Status" },
      ]}
      idKey="artifact_id"
      requiredPermission="artifacts.read / artifacts.create"
      title="Artifacts"
    />
  );
}
