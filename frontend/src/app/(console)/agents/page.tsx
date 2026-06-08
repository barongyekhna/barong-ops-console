import { Bot } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = {
  title: "Agents",
};

export default function AgentsPage() {
  return (
    <EmptyState
      description="Registered agents will appear here."
      icon={Bot}
      title="No agents registered yet."
    />
  );
}
