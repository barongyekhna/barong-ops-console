"use client";

import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { Logo } from "@/components/brand-logo";
import { requiresPasswordChange } from "@/lib/auth";

export function AuthGuard({ children }: { children: ReactNode }) {
  const { status, user } = useAuth();

  if (status === "unauthenticated") {
    redirect("/login");
  }

  if (status !== "authenticated") {
    return (
      <main className="session-screen" aria-live="polite">
        <section className="session-panel session-loading-panel">
          <span className="brand-mark brand-mark-large session-loading-logo">
            <Logo decorative />
          </span>
          <h1>正在进入工作台</h1>
          <p>正在确认会话状态。</p>
        </section>
      </main>
    );
  }

  if (requiresPasswordChange(user)) {
    redirect("/force-password-reset");
  }

  return children;
}
