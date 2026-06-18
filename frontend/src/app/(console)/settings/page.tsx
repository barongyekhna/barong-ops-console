import type { Metadata } from "next";

import { ControlPlaneSettingsView } from "@/components/control-plane-settings-view";

export const metadata: Metadata = {
  title: "Settings",
};

export default function SettingsPage() {
  return <ControlPlaneSettingsView />;
}
