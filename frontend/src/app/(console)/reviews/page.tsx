"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function ReviewsPage() {
  return (
    <ProductResourceConsole
      actions={[
        {
          description: "Record the decision on the selected review.",
          disabled: (record) => Boolean(record.decision),
          endpoint: (record) => `/reviews/${record.review_id}/decision`,
          fields: [
            {
              defaultValue: "approve_demo",
              key: "decision",
              label: "Decision",
              options: [
                { label: "Approve", value: "approve_demo" },
                { label: "Reject", value: "reject_demo" },
                { label: "Request changes", value: "request_changes_demo" },
              ],
              required: true,
              type: "select",
            },
            {
              key: "comment",
              label: "Comment",
              type: "textarea",
            },
          ],
          key: "review-decision",
          label: "Decision",
          submitLabel: "Record decision",
          title: "Review decision",
        },
      ]}
      create={{
        description: "Create a review against an existing job or artifact.",
        endpoint: "/reviews",
        fields: [
          {
            key: "review_id",
            label: "Review ID",
            placeholder: "demo.review",
            required: true,
          },
          {
            key: "job_id",
            label: "Job ID",
          },
          {
            key: "artifact_id",
            label: "Artifact ID",
          },
          {
            defaultValue: "governance_review",
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
        submitLabel: "Create review",
        title: "Create review",
      }}
      description="Manage review records and record governance decisions through existing review APIs."
      detailEndpoint={(record) => `/reviews/${record.review_id}`}
      detailFields={[
        { key: "review_id", label: "Review" },
        { key: "job_id", label: "Job" },
        { key: "artifact_id", label: "Artifact" },
        { key: "review_type", label: "Type" },
        { key: "risk_level", label: "Risk" },
        { key: "status", label: "Status" },
        { key: "decision", label: "Decision" },
        { key: "comment", label: "Comment" },
        { key: "decided_at", label: "Decided" },
      ]}
      emptyDescription="Create reviews from jobs, artifacts, or the form below."
      emptyTitle="No reviews waiting."
      endpoint="/reviews?limit=50&offset=0"
      eyebrow="Governance"
      fields={[
        { key: "review_id", label: "Review" },
        { key: "review_type", label: "Type" },
        { key: "risk_level", label: "Risk" },
        { key: "status", label: "Status" },
      ]}
      idKey="review_id"
      requiredPermission="reviews.read / reviews.approve"
      title="Reviews"
    />
  );
}
