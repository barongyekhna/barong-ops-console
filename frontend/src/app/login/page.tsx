import type { Metadata } from "next";

import { LoginScreen } from "@/components/login-screen";
import { PublicOnly } from "@/components/public-only";

export const metadata: Metadata = {
  title: "Login",
};

export default function LoginPage() {
  return (
    <PublicOnly>
      <LoginScreen />
    </PublicOnly>
  );
}
