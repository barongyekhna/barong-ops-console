import type { Metadata } from "next";

import { CapabilityRecordList } from "@/components/capability-record-list";

export const metadata: Metadata = {
  title: "Reviews",
};

export default function ReviewsPage() {
  return (
    <CapabilityRecordList
      emptyDescription="No review records match the current backend result set."
      emptyTitle="No reviews waiting."
      endpoint="/reviews"
      fields={[
        { key: "review_id", label: "Review ID" },
        { key: "review_type", label: "Type" },
        { key: "status", label: "Status" },
      ]}
      requiredPermission="reviews.read"
      title="Reviews"
    />
  );
}
