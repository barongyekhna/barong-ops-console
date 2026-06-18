"use client";

import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";

export function DashboardAccessControl({
  children,
}: {
  children: ReactNode;
}) {
  const { status } = useAuth();

  if (status === "unauthenticated") {
    redirect("/login");
  }

  if (status !== "authenticated") {
    return null;
  }

  return children;
}
