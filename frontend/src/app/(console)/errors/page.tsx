import { CircleAlert } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = {
  title: "Errors",
};

export default function ErrorsPage() {
  return (
    <EmptyState
      description="Tracked errors will appear here."
      icon={CircleAlert}
      title="No errors recorded."
    />
  );
}
