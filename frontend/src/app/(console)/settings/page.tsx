import type { Metadata } from "next";

import { ControlPlaneSettingsView } from "@/components/control-plane-settings-view";

export const metadata: Metadata = {
  title: "设置",
};

export default function SettingsPage() {
  return <ControlPlaneSettingsView />;
}
