import type { Metadata } from "next";

import { LegalPageShell } from "@/components/legal-page";

export const metadata: Metadata = {
  title: "技术支持",
};

export default function SupportPage() {
  return <LegalPageShell activeKey="support" />;
}
