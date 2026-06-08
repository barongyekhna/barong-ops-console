import { Boxes } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = {
  title: "Modules",
};

export default function ModulesPage() {
  return (
    <EmptyState
      description="Registered modules will appear here."
      icon={Boxes}
      title="No modules registered yet."
    />
  );
}
