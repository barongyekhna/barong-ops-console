import type { Metadata } from "next";

import { LoginScreen } from "@/components/login-screen";

export const metadata: Metadata = {
  title: "Login",
};

export default function LoginPage() {
  return <LoginScreen />;
}
