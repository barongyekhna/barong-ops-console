"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function ErrorsPage() {
  return (
    <ProductResourceConsole
      create={{
        description: "记录一条需要跟进的问题。",
        endpoint: "/errors",
        fields: [
          {
            key: "error_id",
            label: "记录编号",
            required: true,
          },
          {
            defaultValue: "demo_issue",
            key: "error_code",
            label: "问题类型",
            required: true,
          },
          {
            defaultValue: "error_demo",
            key: "severity",
            label: "严重程度",
            options: [
              { label: "提示", value: "info_demo" },
              { label: "警告", value: "warning_demo" },
              { label: "错误", value: "error_demo" },
            ],
            required: true,
            type: "select",
          },
          {
            defaultValue: "open_demo",
            key: "status",
            label: "处理状态",
            options: [
              { label: "待处理", value: "open_demo" },
              { label: "已确认", value: "acknowledged_demo" },
            ],
            required: true,
            type: "select",
          },
          {
            key: "message",
            label: "说明",
            required: true,
            type: "textarea",
          },
          {
            defaultValue: "business.reviews",
            key: "module_key",
            label: "所属功能",
            type: "hidden",
          },
        ],
        submitLabel: "记录",
        title: "记录问题",
      }}
      description="查看和记录需要跟进的问题。"
      detailEndpoint={(record) => `/errors/${record.error_id}`}
      detailFields={[
        { key: "error_code", label: "问题类型" },
        { key: "severity", label: "严重程度" },
        { key: "status", label: "处理状态" },
        { key: "message", label: "说明" },
      ]}
      emptyDescription="当前没有可显示的问题记录。"
      emptyTitle="暂无数据"
      endpoint="/errors?limit=50&offset=0"
      eyebrow="系统"
      fields={[
        { key: "error_code", label: "问题类型" },
        { key: "severity", label: "严重程度" },
        { key: "status", label: "处理状态" },
      ]}
      idKey="error_id"
      requiredPermission="operation_logs.read"
      title="异常记录"
    />
  );
}
