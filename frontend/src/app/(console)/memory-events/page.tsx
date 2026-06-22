"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function MemoryEventsPage() {
  return (
    <ProductResourceConsole
      create={{
        description: "记录一条运行上下文事件。",
        endpoint: "/memory-events",
        fields: [
          {
            key: "memory_event_id",
            label: "记录编号",
            required: true,
          },
          {
            defaultValue: "observation",
            key: "event_type",
            label: "事件类型",
            required: true,
          },
          {
            defaultValue: "system",
            key: "subject_type",
            label: "对象类型",
            required: true,
          },
          {
            key: "subject_id",
            label: "对象编号",
            required: true,
          },
          {
            defaultValue: "normal_demo",
            key: "importance",
            label: "重要程度",
            options: [
              { label: "低", value: "low_demo" },
              { label: "普通", value: "normal_demo" },
              { label: "高", value: "high_demo" },
            ],
            required: true,
            type: "select",
          },
          {
            defaultValue: "{}",
            key: "payload",
            label: "内容",
            type: "json",
          },
        ],
        submitLabel: "记录",
        title: "记录事件",
      }}
      description="查看和记录运行上下文事件。"
      detailEndpoint={(record) => `/memory-events/${record.memory_event_id}`}
      detailFields={[
        { key: "event_type", label: "事件类型" },
        { key: "subject_type", label: "对象类型" },
        { key: "importance", label: "重要程度" },
        { key: "created_at", label: "创建时间" },
      ]}
      emptyDescription="当前没有可显示的运行记录。"
      emptyTitle="暂无数据"
      endpoint="/memory-events?limit=50&offset=0"
      eyebrow="系统"
      fields={[
        { key: "event_type", label: "事件类型" },
        { key: "subject_type", label: "对象类型" },
        { key: "importance", label: "重要程度" },
      ]}
      idKey="memory_event_id"
      requiredPermission="operation_logs.read"
      title="运行记录"
    />
  );
}
