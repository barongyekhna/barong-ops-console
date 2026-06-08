import type { Metadata } from "next";

import { FoundationList } from "@/components/foundation-list";

export const metadata: Metadata = {
  title: "Jobs",
};

export default function JobsPage() {
  return (
    <FoundationList
      emptyDescription="Foundation and demo jobs will appear here."
      emptyTitle="No jobs recorded yet."
      endpoint="/jobs"
      fields={[
        { key: "job_id", label: "Job ID" },
        { key: "module_key", label: "Module" },
        { key: "status", label: "Status" },
      ]}
      title="Jobs"
    />
  );
}
