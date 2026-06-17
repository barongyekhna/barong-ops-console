import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Approvals",
};

export default function ApprovalsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="There are no approval requests waiting for review."
      emptyTitle="No approvals waiting"
      endpoint="/approval/list?limit=50&offset=0"
      fields={[
        { key: "approval_id", label: "Approval ID" },
        { key: "status", label: "Status" },
        { key: "risk_level", label: "Risk" },
      ]}
      requiredPermission="reviews.read"
      title="Approvals"
    />
  );
}
