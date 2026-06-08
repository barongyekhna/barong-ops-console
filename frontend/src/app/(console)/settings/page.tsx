import { Settings } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";

export const metadata: Metadata = {
  title: "Settings",
};

export default function SettingsPage() {
  return (
    <EmptyState
      description="Console settings are not configured in this foundation."
      icon={Settings}
      title="No settings available yet."
    />
  );
}
