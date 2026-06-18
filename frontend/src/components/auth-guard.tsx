"use client";

import { LoaderCircle, RotateCcw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";
import { LoginScreen } from "@/components/login-screen";

const AUTH_LOADING_TIMEOUT_MS = 5_000;

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { status, refresh } = useAuth();
  const [hasTimedOut, setHasTimedOut] = useState(false);
  const shouldRenderShell =
    status === "authenticated" || (status === "checking" && hasTimedOut);
  const shouldFallbackToLogin = status === "unauthenticated";

  useEffect(() => {
    if (shouldFallbackToLogin) {
      router.replace("/login");
    }
  }, [router, shouldFallbackToLogin]);

  useEffect(() => {
    if (status !== "checking") {
      setHasTimedOut(false);
      return;
    }

    const timer = window.setTimeout(() => {
      setHasTimedOut(true);
    }, AUTH_LOADING_TIMEOUT_MS);

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

  if (shouldRenderShell) {
    return children;
  }

  if (shouldFallbackToLogin) {
    return <LoginScreen />;
  }

  return (
    <main className="session-screen" aria-label="Checking session">
      <LoaderCircle className="spin" aria-hidden="true" size={24} />
    </main>
  );
}
