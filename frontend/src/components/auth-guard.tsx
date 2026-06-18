"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { LoginScreen } from "@/components/login-screen";

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { status } = useAuth();
  const shouldFallbackToLogin = status === "unauthenticated";

  useEffect(() => {
    if (shouldFallbackToLogin) {
      router.replace("/login");
    }
  }, [router, shouldFallbackToLogin]);

  if (shouldFallbackToLogin) {
    return <LoginScreen />;
  }

  return children;
}
