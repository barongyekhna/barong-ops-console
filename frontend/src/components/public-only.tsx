"use client";

import { LoaderCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useAuth } from "@/components/auth-provider";

const AUTH_LOADING_TIMEOUT_MS = 5_000;

export function PublicOnly({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { status } = useAuth();
  const [hasTimedOut, setHasTimedOut] = useState(false);
  const shouldRenderPublicContent =
    status !== "authenticated" && (status !== "checking" || hasTimedOut);

  useEffect(() => {
    if (status === "authenticated") {
      router.replace("/dashboard");
    }
  }, [router, status]);

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

  if (status === "authenticated") {
    return (
      <main className="session-screen" aria-label="Checking session">
        <LoaderCircle className="spin" aria-hidden="true" size={24} />
      </main>
    );
  }

  if (shouldRenderPublicContent) {
    return children;
  }

  return (
    <main className="session-screen" aria-label="Checking session">
      <LoaderCircle className="spin" aria-hidden="true" size={24} />
    </main>
  );
}
