import type { Metadata } from "next";

import { LegalPageShell } from "@/components/legal-page";

export const metadata: Metadata = {
  title: "隐私政策",
};

export default function PrivacyPage() {
  return <LegalPageShell activeKey="privacy" />;
}
