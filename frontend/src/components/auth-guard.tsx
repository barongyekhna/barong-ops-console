"use client";

import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { requiresPasswordChange } from "@/lib/auth";

export function AuthGuard({ children }: { children: ReactNode }) {
  const { status, user } = useAuth();

  if (status === "unauthenticated") {
    redirect("/login");
  }

  if (status !== "authenticated") {
    return null;
  }

  if (requiresPasswordChange(user)) {
    redirect("/force-password-reset");
  }

  return children;
}
