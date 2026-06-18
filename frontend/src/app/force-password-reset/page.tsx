import type { Metadata } from "next";

import { ForcePasswordResetForm } from "@/components/force-password-reset-form";

export const metadata: Metadata = {
  title: "Change Password",
};

export default function ForcePasswordResetPage() {
  return <ForcePasswordResetForm />;
}
