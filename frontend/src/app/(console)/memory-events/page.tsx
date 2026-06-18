"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function MemoryEventsPage() {
  return (
    <ProductResourceConsole
      create={{
        description: "Record a memory event for an existing subject or job.",
        endpoint: "/memory-events",
        fields: [
          {
            key: "memory_event_id",
            label: "Memory event ID",
            placeholder: "demo.memory.event",
            required: true,
          },
          {
            defaultValue: "observation",
            key: "event_type",
            label: "Event type",
            required: true,
          },
          {
            defaultValue: "job",
            key: "subject_type",
            label: "Subject type",
            required: true,
          },
          {
            key: "subject_id",
            label: "Subject ID",
            required: true,
          },
          {
            key: "job_id",
            label: "Job ID",
          },
          {
            defaultValue: "normal_demo",
            key: "importance",
            label: "Importance",
            options: [
              { label: "Low", value: "low_demo" },
              { label: "Normal", value: "normal_demo" },
              { label: "High", value: "high_demo" },
            ],
            required: true,
            type: "select",
          },
          {
            defaultValue: "{}",
            key: "payload",
            label: "Payload",
            type: "json",
          },
        ],
        submitLabel: "Record event",
        title: "Record memory event",
      }}
      description="Inspect and record memory event metadata through the existing memory-events API."
      detailEndpoint={(record) => `/memory-events/${record.memory_event_id}`}
      detailFields={[
        { key: "memory_event_id", label: "Event" },
        { key: "event_type", label: "Type" },
        { key: "subject_type", label: "Subject type" },
        { key: "subject_id", label: "Subject ID" },
        { key: "job_id", label: "Job" },
        { key: "importance", label: "Importance" },
        { key: "payload", label: "Payload" },
        { key: "created_at", label: "Created" },
      ]}
      emptyDescription="Memory events appear here when system or job context is recorded."
      emptyTitle="No memory events recorded."
      endpoint="/memory-events?limit=50&offset=0"
      eyebrow="System"
      fields={[
        { key: "memory_event_id", label: "Event" },
        { key: "event_type", label: "Type" },
        { key: "subject_type", label: "Subject" },
        { key: "importance", label: "Importance" },
      ]}
      idKey="memory_event_id"
      requiredPermission="operation_logs.read"
      title="Memory Events"
    />
  );
}
