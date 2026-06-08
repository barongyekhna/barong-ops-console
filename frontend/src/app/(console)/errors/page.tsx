import type { Metadata } from "next";

import { FoundationList } from "@/components/foundation-list";

export const metadata: Metadata = {
  title: "Errors",
};

export default function ErrorsPage() {
  return (
    <FoundationList
      emptyDescription="Foundation error records will appear here."
      emptyTitle="No errors recorded."
      endpoint="/errors"
      fields={[
        { key: "error_id", label: "Error ID" },
        { key: "error_code", label: "Code" },
        { key: "status", label: "Status" },
      ]}
      title="System errors"
    />
  );
}
