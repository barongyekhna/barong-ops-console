"use client";

import { LoaderCircle, RotateCcw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { status, refresh } = useAuth();

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [router, status]);

  if (status === "error") {
    return (
      <main className="session-screen">
        <div className="session-panel">
          <span className="eyebrow">Authentication</span>
          <h1>Session check unavailable</h1>
          <p>The console could not verify the current session.</p>
          <button className="primary-button" onClick={() => void refresh()}>
            <RotateCcw aria-hidden="true" size={17} />
            Retry
          </button>
        </div>
      </main>
    );
  }

  if (status !== "authenticated") {
    return (
      <main className="session-screen" aria-label="Checking session">
        <LoaderCircle className="spin" aria-hidden="true" size={24} />
      </main>
    );
  }

  return children;
}

export function PublicOnly({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { status } = useAuth();

  useEffect(() => {
    if (status === "authenticated") {
      router.replace("/dashboard");
    }
  }, [router, status]);

  if (status === "authenticated" || status === "checking") {
    return (
      <main className="session-screen" aria-label="Checking session">
        <LoaderCircle className="spin" aria-hidden="true" size={24} />
      </main>
    );
  }

  return children;
}
