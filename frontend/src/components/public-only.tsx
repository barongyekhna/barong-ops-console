"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { requiresPasswordChange } from "@/lib/auth";

export function PublicOnly({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { status, user } = useAuth();

  useEffect(() => {
    if (status === "authenticated") {
      router.replace(
        requiresPasswordChange(user) ? "/force-password-reset" : "/dashboard",
      );
    }
  }, [router, status, user]);

  if (status === "authenticated") {
    return null;
  }

  return children;
}
