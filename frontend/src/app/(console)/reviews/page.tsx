import type { Metadata } from "next";

import { FoundationList } from "@/components/foundation-list";

export const metadata: Metadata = {
  title: "Reviews",
};

export default function ReviewsPage() {
  return (
    <FoundationList
      emptyDescription="Foundation review items will appear here."
      emptyTitle="No reviews waiting."
      endpoint="/reviews"
      fields={[
        { key: "review_id", label: "Review ID" },
        { key: "review_type", label: "Type" },
        { key: "status", label: "Status" },
      ]}
      title="Reviews"
    />
  );
}
