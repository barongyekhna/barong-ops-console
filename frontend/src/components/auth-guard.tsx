"use client";

import { LoaderCircle, RotateCcw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";

const FALLBACK_DELAY_MS = 3000;

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { status, refresh } = useAuth();
  const [showFallback, setShowFallback] = useState(false);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [router, status]);

  useEffect(() => {
    if (status !== "checking") {
      setShowFallback(false);
      return;
    }

    const timer = window.setTimeout(() => {
      setShowFallback(true);
    }, FALLBACK_DELAY_MS);

    return () => {
      window.clearTimeout(timer);
    };
  }, [status]);

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
    if (showFallback) {
      return (
        <main className="session-screen" aria-label="System initializing">
          <div className="session-panel">
            <span className="eyebrow">Fallback mode active</span>
            <h1>System initializing</h1>
            <p>Fallback mode active</p>
            <button className="primary-button" onClick={() => void refresh()}>
              <RotateCcw aria-hidden="true" size={17} />
              Try refresh
            </button>
          </div>
        </main>
      );
    }

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
