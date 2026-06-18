"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function ProductsPage() {
  return (
    <ProductResourceConsole
      actions={[
        {
          buildPayload: (values, record) => ({
            ...values,
            module_key: record.module_key,
            risk_level: "low",
            status: "pending",
          }),
          description: "Create a metadata-only product preparation job for the selected product adapter.",
          disabled: (record) => record.module_key !== "business.products",
          endpoint: "/jobs",
          fields: [
            {
              key: "job_id",
              label: "Job ID",
              placeholder: "demo.product.prepare",
              required: true,
            },
            {
              defaultValue: "{}",
              key: "input_payload",
              label: "Input payload",
              type: "json",
            },
          ],
          key: "product-prepare",
          label: "Prepare",
          submitLabel: "Create job",
          title: "Product prepare action",
        },
      ]}
      description="Expose product module capability, adapter binding, and the existing metadata-only job action surface."
      detailFields={[
        { key: "adapter_key", label: "Adapter" },
        { key: "module_key", label: "Module" },
        { key: "adapter_status", label: "Status" },
        { key: "supported_surfaces", label: "Surfaces" },
        { key: "action_contracts", label: "Actions" },
        { key: "api_bindings", label: "API bindings" },
        { key: "route_bindings", label: "Routes" },
      ]}
      emptyDescription="Product adapter metadata appears here when the module adapter registry is available."
      emptyTitle="No product adapter records returned."
      endpoint="/module-adapters/registry"
      eyebrow="Extensions"
      fields={[
        { key: "adapter_key", label: "Adapter" },
        { key: "module_key", label: "Module" },
        { key: "adapter_status", label: "Status" },
        { key: "supported_surfaces", label: "Surfaces" },
      ]}
      idKey="adapter_key"
      requiredPermission="products.read / jobs.create"
      title="Products"
    />
  );
}
