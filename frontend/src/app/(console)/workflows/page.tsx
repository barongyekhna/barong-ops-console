"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function WorkflowsPage() {
  return (
    <ProductResourceConsole
      actions={[
        {
          buildPayload: (values, record) => ({
            ...values,
            risk_level: "low",
            status: "pending",
            workflow_key: record.workflow_key,
          }),
          description: "Create a job that references the selected workflow.",
          endpoint: "/jobs",
          fields: [
            {
              key: "job_id",
              label: "Job ID",
              placeholder: "demo.workflow.job",
              required: true,
            },
            {
              defaultValue: "business.products",
              key: "module_key",
              label: "Module key",
              required: true,
            },
            {
              defaultValue: "{}",
              key: "input_payload",
              label: "Input payload",
              type: "json",
            },
          ],
          key: "start-workflow-job",
          label: "Start job",
          submitLabel: "Start job",
          title: "Workflow execution",
        },
      ]}
      create={{
        description: "Register a safe metadata-only workflow.",
        endpoint: "/workflows",
        fields: [
          {
            key: "workflow_key",
            label: "Workflow key",
            placeholder: "demo.workflow",
            required: true,
          },
          {
            key: "name",
            label: "Name",
            required: true,
          },
          {
            defaultValue: "metadata_only",
            key: "engine",
            label: "Engine",
            required: true,
          },
          {
            defaultValue: "foundation://metadata-only",
            key: "endpoint_ref",
            label: "Endpoint reference",
            required: true,
          },
          {
            defaultValue: "foundation",
            key: "status",
            label: "Status",
            options: [
              { label: "Foundation", value: "foundation" },
              { label: "Demo", value: "demo" },
              { label: "Draft demo", value: "draft_demo" },
              { label: "Inactive demo", value: "inactive_demo" },
            ],
            required: true,
            type: "select",
          },
          {
            defaultValue: "60",
            key: "timeout_seconds",
            label: "Timeout seconds",
            required: true,
            type: "number",
          },
          {
            defaultValue: "{}",
            key: "callback_contract",
            label: "Callback contract",
            type: "json",
          },
          {
            defaultValue: "{}",
            key: "retry_policy",
            label: "Retry policy",
            type: "json",
          },
        ],
        submitLabel: "Create workflow",
        title: "Create workflow",
      }}
      description="Manage workflow registry records and create job execution requests from selected workflows."
      detailEndpoint={(record) => `/workflows/${record.workflow_key}`}
      detailFields={[
        { key: "workflow_key", label: "Workflow" },
        { key: "name", label: "Name" },
        { key: "engine", label: "Engine" },
        { key: "endpoint_ref", label: "Endpoint" },
        { key: "status", label: "Status" },
        { key: "timeout_seconds", label: "Timeout" },
        { key: "callback_contract", label: "Callback contract" },
        { key: "retry_policy", label: "Retry policy" },
      ]}
      emptyDescription="Register a workflow to make it available for job requests."
      emptyTitle="No execution workflows yet."
      endpoint="/workflows?limit=50&offset=0"
      eyebrow="Execution"
      fields={[
        { key: "workflow_key", label: "Workflow" },
        { key: "name", label: "Name" },
        { key: "engine", label: "Engine" },
        { key: "status", label: "Status" },
      ]}
      idKey="workflow_key"
      requiredPermission="modules.read / jobs.create"
      title="Workflows"
    />
  );
}
