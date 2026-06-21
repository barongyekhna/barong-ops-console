"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function AgentsPage() {
  return (
    <ProductResourceConsole
      create={{
        description: "Register a foundation agent and its allowed module scope.",
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
              placeholder: "business.reviews",
              type: "csv",
            },
        ],
        submitLabel: "Create agent",
        title: "Create agent",
      }}
      description="Expose the agent registry with detail inspection."
      detailEndpoint={(record) => `/agents/${record.agent_key}`}
      detailFields={[
        { key: "agent_key", label: "Agent" },
        { key: "name", label: "Name" },
        { key: "status", label: "Status" },
        { key: "risk_level", label: "Risk" },
        { key: "allowed_module_keys", label: "Allowed modules" },
        { key: "created_at", label: "Created" },
      ]}
      emptyDescription="Register an agent to connect it to module metadata."
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
      requiredPermission="modules.read"
      title="Agents"
    />
  );
}
