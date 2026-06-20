"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function ErrorsPage() {
  return (
    <ProductResourceConsole
      create={{
        description: "Record a system issue against a module or correlation ID.",
        endpoint: "/errors",
        fields: [
          {
            key: "error_id",
            label: "Error ID",
            placeholder: "demo.error",
            required: true,
          },
          {
            defaultValue: "demo_issue",
            key: "error_code",
            label: "Code",
            required: true,
          },
          {
            defaultValue: "error_demo",
            key: "severity",
            label: "Severity",
            options: [
              { label: "Info", value: "info_demo" },
              { label: "Warning", value: "warning_demo" },
              { label: "Error", value: "error_demo" },
            ],
            required: true,
            type: "select",
          },
          {
            defaultValue: "open_demo",
            key: "status",
            label: "Status",
            options: [
              { label: "Open", value: "open_demo" },
              { label: "Acknowledged", value: "acknowledged_demo" },
            ],
            required: true,
            type: "select",
          },
          {
            key: "message",
            label: "Message",
            required: true,
            type: "textarea",
          },
          {
            defaultValue: "business.products",
            key: "module_key",
            label: "Module key",
          },
          {
            key: "correlation_id",
            label: "Correlation ID",
          },
          {
            defaultValue: "{}",
            key: "details",
            label: "Details",
            type: "json",
          },
        ],
        submitLabel: "Record error",
        title: "Record error",
      }}
      description="Inspect and record operational error metadata through the existing errors API."
      detailEndpoint={(record) => `/errors/${record.error_id}`}
      detailFields={[
        { key: "error_id", label: "Error" },
        { key: "error_code", label: "Code" },
        { key: "severity", label: "Severity" },
        { key: "status", label: "Status" },
        { key: "message", label: "Message" },
        { key: "module_key", label: "Module" },
        { key: "correlation_id", label: "Correlation" },
        { key: "details", label: "Details" },
      ]}
      emptyDescription="Record an error or connect a producer that writes system issue metadata."
      emptyTitle="No system issues recorded."
      endpoint="/errors?limit=50&offset=0"
      eyebrow="System"
      fields={[
        { key: "error_id", label: "Error" },
        { key: "error_code", label: "Code" },
        { key: "severity", label: "Severity" },
        { key: "status", label: "Status" },
      ]}
      idKey="error_id"
      requiredPermission="operation_logs.read"
      title="Errors"
    />
  );
}
