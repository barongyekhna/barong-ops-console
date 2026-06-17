import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Jobs",
};

export default function JobsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="No operation jobs match the current backend result set."
      emptyTitle="No jobs recorded yet."
      endpoint="/jobs"
      fields={[
        { key: "job_id", label: "Job ID" },
        { key: "module_key", label: "Module" },
        { key: "status", label: "Status" },
      ]}
      requiredPermission="jobs.read"
      title="Jobs"
    />
  );
}
