"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function AgentsPage() {
  return (
    <ProductResourceConsole
      actions={[
        {
          buildPayload: (values, record) => ({
            ...values,
            agent_key: record.agent_key,
            risk_level: "low",
            status: "pending",
          }),
          description: "Create a job request assigned to the selected agent.",
          endpoint: "/jobs",
          fields: [
            {
              key: "job_id",
              label: "Job ID",
              placeholder: "demo.agent.job",
              required: true,
            },
            {
              defaultValue: "business.products",
              key: "module_key",
              label: "Module key",
              required: true,
            },
            {
              key: "workflow_key",
              label: "Workflow key",
            },
            {
              defaultValue: "{}",
              key: "input_payload",
              label: "Input payload",
              type: "json",
            },
          ],
          key: "agent-job",
          label: "Create job",
          submitLabel: "Create job",
          title: "Agent execution request",
        },
      ]}
      create={{
        description: "Register a foundation agent and its allowed module/workflow scope.",
        endpoint: "/agents",
        fields: [
          {
            key: "agent_key",
            label: "Agent key",
            placeholder: "demo.agent",
            required: true,
          },
          {
            key: "name",
            label: "Name",
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
            defaultValue: "low",
            key: "risk_level",
            label: "Risk level",
            required: true,
          },
          {
            key: "allowed_module_keys",
            label: "Allowed modules",
            placeholder: "business.products, business.jobs",
            type: "csv",
          },
          {
            key: "allowed_workflow_keys",
            label: "Allowed workflows",
            type: "csv",
          },
        ],
        submitLabel: "Create agent",
        title: "Create agent",
      }}
      description="Expose the agent registry with detail inspection and job request creation."
      detailEndpoint={(record) => `/agents/${record.agent_key}`}
      detailFields={[
        { key: "agent_key", label: "Agent" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
        { key: "risk_level", label: "Risk" },
        { key: "allowed_module_keys", label: "Allowed modules" },
        { key: "allowed_workflow_keys", label: "Allowed workflows" },
        { key: "created_at", label: "Created" },
      ]}
      emptyDescription="Register an agent to connect it to job requests and workflow metadata."
      emptyTitle="No automation records yet."
      endpoint="/agents?limit=50&offset=0"
      eyebrow="Extensions"
      fields={[
        { key: "agent_key", label: "Agent" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
        { key: "risk_level", label: "Risk" },
      ]}
      idKey="agent_key"
      requiredPermission="modules.read / jobs.create"
      title="Agents"
    />
  );
}
