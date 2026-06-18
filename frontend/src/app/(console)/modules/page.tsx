"use client";

import { ModuleRegistryProductView } from "@/components/module-registry-product-view";
import { ProductResourceConsole } from "@/components/product-resource-console";

export default function ModulesPage() {
  return (
    <div className="product-page-stack">
      <ModuleRegistryProductView />
      <ProductResourceConsole
        create={{
          description: "Create a foundation module metadata record.",
          endpoint: "/modules",
          fields: [
            {
              key: "module_key",
              label: "Module key",
              placeholder: "demo.module",
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
              defaultValue: "{}",
              key: "input_schema",
              label: "Input schema",
              type: "json",
            },
            {
              defaultValue: "{}",
              key: "output_schema",
              label: "Output schema",
              type: "json",
            },
          ],
          submitLabel: "Create module",
          title: "Create module",
        }}
        description="Manage control-plane module resource records in addition to the registry/capability map above."
        detailEndpoint={(record) => `/modules/${record.module_key}`}
        detailFields={[
          { key: "module_key", label: "Module" },
          { key: "name", label: "Name" },
          { key: "status", label: "Status" },
          { key: "risk_level", label: "Risk" },
          { key: "input_schema", label: "Input schema" },
          { key: "output_schema", label: "Output schema" },
          { key: "created_at", label: "Created" },
        ]}
        emptyDescription="Create a module resource record when registry metadata needs a persisted resource entry."
        emptyTitle="No module resource records yet."
        endpoint="/modules?limit=50&offset=0"
        eyebrow="Control plane"
        fields={[
          { key: "module_key", label: "Module" },
          { key: "name", label: "Name" },
          { key: "status", label: "Status" },
          { key: "risk_level", label: "Risk" },
        ]}
        idKey="module_key"
        requiredPermission="modules.read / modules.manage"
        title="Module Resources"
      />
    </div>
  );
}
