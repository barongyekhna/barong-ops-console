import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Jobs (Records)",
};

export default function JobsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="No job records match the current view."
      emptyTitle="No jobs recorded yet."
      endpoint="/jobs"
      fields={[
        { key: "job_id", label: "Job ID" },
        { key: "module_key", label: "Area" },
        { key: "status", label: "Status" },
      ]}
      requiredPermission="jobs.read"
      title="Jobs (Records)"
    />
  );
}
