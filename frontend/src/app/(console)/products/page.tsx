"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function ProductsPage() {
  return (
    <ProductResourceConsole
      description="Expose product module capability and adapter binding metadata."
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
      requiredPermission="products.read"
      title="Products"
    />
  );
}
