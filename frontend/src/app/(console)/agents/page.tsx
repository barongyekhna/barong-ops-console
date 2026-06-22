"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

export default function AgentsPage() {
  return (
    <ProductResourceConsole
      create={{
        description: "登记一个自动化助手。",
        endpoint: "/agents",
        fields: [
          {
            key: "agent_key",
            label: "助手编号",
            required: true,
          },
          {
            key: "name",
            label: "名称",
            required: true,
          },
          {
            defaultValue: "foundation",
            key: "status",
            label: "状态",
            options: [
              { label: "基础", value: "foundation" },
              { label: "演示", value: "demo" },
              { label: "草稿", value: "draft_demo" },
              { label: "停用", value: "inactive_demo" },
            ],
            required: true,
            type: "select",
          },
          {
            defaultValue: "low",
            key: "risk_level",
            label: "风险等级",
            required: true,
          },
        ],
        submitLabel: "创建",
        title: "创建助手",
      }}
      description="查看已登记的自动化助手。"
      detailEndpoint={(record) => `/agents/${record.agent_key}`}
      detailFields={[
        { key: "name", label: "名称" },
        { key: "status", label: "状态" },
        { key: "risk_level", label: "风险等级" },
        { key: "created_at", label: "创建时间" },
      ]}
      emptyDescription="当前没有可显示的助手。"
      emptyTitle="暂无数据"
      endpoint="/agents?limit=50&offset=0"
      eyebrow="扩展能力"
      fields={[
        { key: "name", label: "名称" },
        { key: "status", label: "状态" },
        { key: "risk_level", label: "风险等级" },
      ]}
      idKey="agent_key"
      requiredPermission="modules.read"
      title="自动化助手"
    />
  );
}
