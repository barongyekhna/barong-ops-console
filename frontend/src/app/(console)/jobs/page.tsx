"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function JobsPage() {
  return (
    <ProductResourceConsole
      actions={[
        {
          description: "Append a safe status event to the selected job.",
          endpoint: (record) => `/jobs/${record.job_id}/events`,
          fields: [
            {
              defaultValue: "status_change",
              key: "event_type",
              label: "Event type",
              type: "hidden",
            },
            {
              defaultValue: "running",
              key: "to_status",
              label: "New status",
              options: [
                { label: "Running", value: "running" },
                { label: "Waiting callback", value: "waiting_callback" },
                { label: "Waiting review", value: "waiting_review" },
                { label: "Failed", value: "failed" },
                { label: "Cancelled", value: "cancelled" },
                { label: "Completed demo", value: "completed_demo" },
              ],
              required: true,
              type: "select",
            },
            {
              defaultValue: "{}",
              key: "details",
              label: "Event details",
              type: "json",
            },
          ],
          key: "job-event",
          label: "Append event",
          submitLabel: "Append event",
          title: "Job execution event",
        },
      ]}
      create={{
        description: "Create a metadata-only job request through the existing jobs API.",
        endpoint: "/jobs",
        fields: [
          {
            key: "job_id",
            label: "Job ID",
            placeholder: "demo.job.request",
            required: true,
          },
          {
            defaultValue: "business.products",
            key: "module_key",
            label: "Module key",
            required: true,
          },
          {
            key: "agent_key",
            label: "Agent key",
          },
          {
            key: "workflow_key",
            label: "Workflow key",
          },
          {
            defaultValue: "pending",
            key: "status",
            label: "Status",
            options: [
              { label: "Pending", value: "pending" },
              { label: "Draft", value: "draft" },
            ],
            required: true,
            type: "select",
          },
          {
            defaultValue: "low",
            key: "risk_level",
            label: "Risk level",
            required: true,
          },
          {
            defaultValue: "{}",
            key: "input_payload",
            label: "Input payload",
            type: "json",
          },
        ],
        submitLabel: "Create job",
        title: "Create job",
      }}
      description="Create, inspect, and advance metadata-only job records through the existing jobs endpoints."
      detailEndpoint={(record) => `/jobs/${record.job_id}`}
      detailFields={[
        { key: "job_id", label: "Job ID" },
        { key: "module_key", label: "Module" },
        { key: "agent_key", label: "Agent" },
        { key: "workflow_key", label: "Workflow" },
        { key: "status", label: "Status" },
        { key: "risk_level", label: "Risk" },
        { key: "input_payload", label: "Input payload" },
        { key: "created_at", label: "Created" },
        { key: "updated_at", label: "Updated" },
      ]}
      emptyDescription="Create a job request or connect a producer that writes job metadata."
      emptyTitle="No jobs recorded yet."
      endpoint="/jobs?limit=50&offset=0"
      eyebrow="Execution"
      fields={[
        { key: "job_id", label: "Job ID" },
        { key: "module_key", label: "Module" },
        { key: "workflow_key", label: "Workflow" },
        { key: "status", label: "Status" },
      ]}
      idKey="job_id"
      listRequest={{
        fallbackToEmptyOnError: true,
        retryLimit: 1,
        timeoutMs: 15_000,
      }}
      relatedLists={[
        {
          endpoint: (record) => `/jobs/${record.job_id}/events?limit=20&offset=0`,
          fields: [
            { key: "event_type", label: "Event" },
            { key: "from_status", label: "From" },
            { key: "to_status", label: "To" },
            { key: "created_at", label: "Created" },
          ],
          key: "job-events",
          title: "Job events",
        },
      ]}
      requiredPermission="jobs.read / jobs.create"
      title="Jobs"
    />
  );
}
