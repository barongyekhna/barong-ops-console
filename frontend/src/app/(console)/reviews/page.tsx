import { ClipboardCheck } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = {
  title: "Reviews",
};

export default function ReviewsPage() {
  return (
    <EmptyState
      description="Review items will appear here."
      icon={ClipboardCheck}
      title="No reviews waiting."
    />
  );
}
