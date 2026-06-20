"use client";

import { ProductResourceConsole } from "@/components/product-resource-console";

function approvalIsNotPending(record: Record<string, unknown>) {
  const approval = record.approval;
  if (typeof approval !== "object" || approval === null) {
    return false;
  }

  return (approval as { status?: unknown }).status !== "pending";
}

export default function ApprovalsPage() {
  return (
    <ProductResourceConsole
      actions={[
        {
          description: "Approve the selected approval request. This records the decision only.",
          disabled: approvalIsNotPending,
          endpoint: (record) => `/approval/${record.approval_id}/approve`,
          fields: [
            {
              key: "reason",
              label: "Reason",
              required: true,
              type: "textarea",
            },
          ],
          key: "approve",
          label: "Approve",
          submitLabel: "Approve",
          title: "Approve request",
        },
        {
          description: "Reject the selected approval request. This records the decision only.",
          disabled: approvalIsNotPending,
          endpoint: (record) => `/approval/${record.approval_id}/reject`,
          fields: [
            {
              key: "reason",
              label: "Reason",
              required: true,
              type: "textarea",
            },
          ],
          key: "reject",
          label: "Reject",
          submitLabel: "Reject",
          title: "Reject request",
          variant: "danger",
        },
      ]}
      create={{
        description: "Create an approval request for a module/action pair.",
        endpoint: "/approval/request",
        fields: [
          {
            key: "approval_id",
            label: "Approval ID",
            placeholder: "demo.approval",
          },
          {
            key: "execution_id",
            label: "Execution ID",
            placeholder: "demo.execution",
            required: true,
          },
          {
            defaultValue: "business.products",
            key: "module_key",
            label: "Module key",
            required: true,
          },
          {
            defaultValue: "business.products.placeholder.adapter",
            key: "adapter_key",
            label: "Adapter key",
            required: true,
          },
          {
            defaultValue: "business.products.placeholder.prepare",
            key: "action_key",
            label: "Action key",
            required: true,
          },
          {
            defaultValue: "medium",
            key: "risk_level",
            label: "Risk",
            options: [
              { label: "Low", value: "low" },
              { label: "Medium", value: "medium" },
              { label: "High", value: "high" },
            ],
            required: true,
            type: "select",
          },
          {
            defaultValue: "mock",
            key: "execution_type",
            label: "Execution type",
            options: [
              { label: "Mock", value: "mock" },
              { label: "No-op", value: "no_op" },
              { label: "Async", value: "async" },
              { label: "Real", value: "real" },
            ],
            required: true,
            type: "select",
          },
          {
            key: "reason",
            label: "Reason",
            required: true,
            type: "textarea",
          },
        ],
        submitLabel: "Create approval",
        title: "Create approval",
      }}
      description="Review approval requests, inspect safety boundaries, and record approve/reject decisions."
      detailEndpoint={(record) => `/approval/${record.approval_id}`}
      detailFields={[
        { key: "approval.approval_id", label: "Approval" },
        { key: "approval.execution_id", label: "Execution" },
        { key: "approval.module_key", label: "Module" },
        { key: "approval.action_key", label: "Action" },
        { key: "approval.status", label: "Status" },
        { key: "permission_boundary.actor_role", label: "Actor role" },
        { key: "permission_boundary.allowed_actions", label: "Allowed actions" },
        { key: "safety.no_execution", label: "No execution" },
      ]}
      emptyDescription="Approval requests appear here when execution flows require governance."
      emptyTitle="No approvals waiting"
      endpoint="/approval/list?limit=50&offset=0"
      eyebrow="Governance"
      fields={[
        { key: "approval_id", label: "Approval" },
        { key: "module_key", label: "Module" },
        { key: "risk_level", label: "Risk" },
        { key: "status", label: "Status" },
      ]}
      idKey="approval_id"
      requiredPermission="reviews.read / reviews.approve"
      title="Approvals"
    />
  );
}
