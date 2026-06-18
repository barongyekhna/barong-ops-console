"use client";

import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";

export function AuthGuard({ children }: { children: ReactNode }) {
  const { status, user } = useAuth();

  if (status === "unauthenticated") {
    redirect("/login");
  }

  if (status !== "authenticated") {
    return null;
  }

  if (user?.must_change_password) {
    redirect("/force-password-reset");
  }

  return children;
}
