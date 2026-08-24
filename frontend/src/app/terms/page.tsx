import type { Metadata } from "next";

import { LegalPageShell } from "@/components/legal-page";

export const metadata: Metadata = {
  title: "使用规范",
};

export default function TermsPage() {
  return <LegalPageShell activeKey="terms" />;
}
